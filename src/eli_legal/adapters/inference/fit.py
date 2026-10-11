"""How a model is placed on this machine: context length, layers on the graphics card, batch.

Nothing here knows a model or a machine by name. The inputs are the model's own costs (from its
file, ``gguf_sizes``) and the memory free now (``hardware``); the output is a plan and the reasons
for it. The arithmetic is ELI's (``eli.core.hardware_profile``): graphics memory needed is the
weights of the layers placed there, the share of the KV cache that follows those layers, the
compute buffers llama.cpp allocates at the first generation, and the backend's own overhead; what
does not go to the card must fit the share of system memory a model may take.

When not everything fits (``balanced``, the default) the context the work needs is kept, the
batch gives way first, then layers. ``max_gpu`` keeps the layers and gives up context instead;
``max_ctx`` keeps the context whatever it costs in layers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from eli_legal.adapters.inference import gguf_sizes, hardware
from eli_legal.adapters.inference.hardware import (
    Hardware,
    cpu_ram_budget_mb,
    recommend_threads,
    vram_reserve_mb,
)

MIB = 1024 * 1024

MIN_CTX = 2048  # below this no step of the work fits; also the smallest the settings accept
CTX_UNIT = 256  # contexts are whole multiples of this
DEFAULT_BATCH = 512  # llama.cpp's own default
MIN_BATCH = 128
# Memory the graphics backend takes for itself once a model is on the card (measured by ELI on
# CUDA; Vulkan and Metal take less, so this errs safe).
BACKEND_OVERHEAD_MB = 350.0
# Of the model's trained context, the share "automatic" aims for, and of the memory left after
# the weights, the share the KV cache may take. Proportions, not sizes; the environment
# variables change them for this machine.
CTX_FRACTION = 0.9
CTX_KV_SHARE = 0.5

PRIORITIES = ("balanced", "max_gpu", "max_ctx")


def _fraction(name: str, default: float) -> float:
    try:
        return max(0.05, min(1.0, float(os.environ.get(name, "") or default)))
    except ValueError:
        return default


def compute_reserve_mb(n_ctx: int, batch: int) -> float:
    """The buffers llama.cpp allocates at the first generation, not at load: they grow with the
    context (attention scratch) and the batch (activations), never with which model it is.
    Leaving them out is how a model loads and then fails on its first answer. ELI's measured
    estimate, erring high: 256 MB, 24 MB per thousand tokens of context, 1.5 MB per batch unit."""
    return 256.0 + (max(0, n_ctx) / 1024.0) * 24.0 + max(0, batch) * 1.5


@dataclass(frozen=True, slots=True)
class ModelCost:
    """A model's own memory costs, from its file."""

    weights: gguf_sizes.Weights
    kv_bytes_per_token: float
    kv_source: str  # measured | estimated
    experts_in_ram: bool = False

    @property
    def blocks(self) -> int:
        return self.weights.blocks

    @property
    def slots(self) -> int:
        """Layer counts llama.cpp distinguishes: every block, and one more for the output head."""
        return self.weights.blocks + 1

    @property
    def total_mb(self) -> float:
        return self.weights.total / MIB

    def gpu_weights_mb(self, layers: int) -> float:
        return self.weights.gpu_bytes(layers, experts_in_ram=self.experts_in_ram) / MIB

    def kv_mb(self, ctx: int, gpu_layers: int | None = None) -> float:
        """KV cache for ctx tokens; with gpu_layers, the share that lives on the card (llama.cpp
        keeps each layer's cache on that layer's device)."""
        total = max(0, ctx) * self.kv_bytes_per_token / MIB
        if gpu_layers is None:
            return total
        return total * min(1.0, max(0, gpu_layers) / max(1, self.blocks))

    def cpu_weights_mb(self, gpu_layers: int) -> float:
        on_card = self.weights.gpu_bytes(gpu_layers, experts_in_ram=self.experts_in_ram)
        return max(0, self.weights.total - on_card) / MIB


def model_cost(model_path: str | Path, *, experts_in_ram: bool = False) -> ModelCost | None:
    """The model's costs, or None when its file cannot be read as GGUF."""
    w = gguf_sizes.weights(model_path)
    kv = gguf_sizes.kv_elements_per_token(model_path)
    if w is None or kv is None:
        return None
    per_token = (kv[0] + kv[1]) * gguf_sizes.bytes_per_element("f16")
    return ModelCost(w, per_token, kv[2], experts_in_ram)


def needed_mb(cost: ModelCost, ctx: int, layers: int, batch: int) -> float:
    """Graphics memory for this placement."""
    return (
        cost.gpu_weights_mb(layers)
        + cost.kv_mb(ctx, gpu_layers=layers)
        + compute_reserve_mb(ctx, batch)
        + BACKEND_OVERHEAD_MB
    )


def cpu_spill_mb(cost: ModelCost, ctx: int, layers: int, batch: int) -> float:
    """System memory for what is not on the card: those weights, their share of the KV cache,
    and with nothing on the card a share of the compute buffers."""
    spill = cost.cpu_weights_mb(layers) + cost.kv_mb(ctx) - cost.kv_mb(ctx, gpu_layers=layers)
    if layers <= 0:
        spill += compute_reserve_mb(ctx, batch) * 0.25
    return spill + 256.0


def _ctx_step(ctx: int) -> int:
    """How far to move the context at once: a sixteenth of it, in whole units."""
    return max(CTX_UNIT, (ctx // 16 // CTX_UNIT) * CTX_UNIT)


def _ceiling(cost: ModelCost, user_layers: int | None) -> int:
    """The most layers a fit may return. A count given by the administrator is a ceiling: a fit
    reduces it, never raises it."""
    if user_layers is None or user_layers >= cost.blocks:
        return cost.slots
    return max(0, user_layers)


def _fit_balanced(
    cost: ModelCost, budget: float, ctx: int, batch: int, min_ctx: int, user_layers: int | None
) -> tuple[int, int, int]:
    """Keep the context. What gives way: the batch (it costs a little speed while a prompt is
    read), then layers, one at a time. If no layer fits beside this context the model runs on
    the processor with the context it needs, rather than on the card with one too short to
    work in. Memory left over goes back to the batch.

    More free memory never gives fewer layers: the layer count is the most that fit at the
    smallest batch. (ELI sheds layers to a quarter before it touches the batch, which can give
    a machine with less free memory one layer more than a machine with more.)"""
    ceiling = _ceiling(cost, user_layers)
    if budget <= 0:
        return ctx, 0, batch
    full_batch, layers = batch, ceiling
    while batch > MIN_BATCH and needed_mb(cost, ctx, layers, batch) > budget:
        batch = max(MIN_BATCH, batch // 2)
    while layers > 0 and needed_mb(cost, ctx, layers, batch) > budget:
        layers -= 1
    if layers <= 0:
        return ctx, 0, full_batch
    while batch * 2 <= full_batch and needed_mb(cost, ctx, layers, batch * 2) <= budget:
        batch *= 2
    return ctx, layers, batch


def _fit_max_gpu(
    cost: ModelCost, budget: float, ctx: int, batch: int, min_ctx: int, user_layers: int | None
) -> tuple[int, int, int]:
    """Keep the layers: shrink context and batch before shedding any."""
    ceiling = _ceiling(cost, user_layers)
    layers = ceiling
    if budget <= 0:
        return ctx, 0, batch
    step = max(1, cost.slots // 10)
    while needed_mb(cost, ctx, layers, batch) > budget:
        if ctx > min_ctx:
            ctx = max(min_ctx, ctx - _ctx_step(ctx))
        elif batch > MIN_BATCH:
            batch = max(MIN_BATCH, batch // 2)
        else:
            break
    while layers > 0 and needed_mb(cost, ctx, layers, batch) > budget:
        layers = max(0, layers - step)
    while layers < ceiling and needed_mb(cost, ctx, layers + 1, batch) <= budget:
        layers += 1
    return ctx, layers, batch


def _fit_max_ctx(
    cost: ModelCost, budget: float, ctx: int, batch: int, min_ctx: int, user_layers: int | None
) -> tuple[int, int, int]:
    """Keep the context whatever it costs in layers; add layers only where it stays."""
    ceiling = _ceiling(cost, user_layers)
    layers = ceiling
    if budget <= 0:
        return ctx, 0, batch
    if needed_mb(cost, ctx, layers, batch) > budget:
        layers = 0
        while batch > MIN_BATCH and needed_mb(cost, ctx, 0, batch) > budget:
            batch = max(MIN_BATCH, batch // 2)
        while ctx > min_ctx and needed_mb(cost, ctx, 0, batch) > budget:
            ctx = max(min_ctx, ctx - _ctx_step(ctx))
    while layers < ceiling and needed_mb(cost, ctx, layers + 1, batch) <= budget:
        layers += 1
    return ctx, layers, batch


_FITS = {"balanced": _fit_balanced, "max_gpu": _fit_max_gpu, "max_ctx": _fit_max_ctx}


def _clamp_to_ram(
    cost: ModelCost,
    vram_budget: float,
    ram_budget: float,
    ctx: int,
    layers: int,
    batch: int,
    min_ctx: int,
    user_layers: int | None,
) -> tuple[int, int, int]:
    """What stays off the card must fit the system-memory budget."""
    ceiling = _ceiling(cost, user_layers)
    for _ in range(256):
        if cpu_spill_mb(cost, ctx, layers, batch) <= ram_budget:
            break
        if layers < ceiling and needed_mb(cost, ctx, layers + 1, batch) <= vram_budget:
            layers += 1
            continue
        # With any layer on the card the shortfall is weights, which are mapped from the file
        # and paged in as needed: slower, not fatal, and no context length changes it.
        if layers > 0:
            break
        if batch > MIN_BATCH:
            batch = max(MIN_BATCH, batch // 2)
        elif ctx > min_ctx:
            ctx = max(min_ctx, ctx - _ctx_step(ctx))
        else:
            break
    return ctx, layers, batch


def auto_context_limits(
    cost: ModelCost, trained: int, *, free_vram_mb: int, ram_budget_mb: int
) -> tuple[int, int]:
    """(wanted, cap): the model's trained context times CTX_FRACTION (0 when the file does not
    say), and the context whose KV cache fits CTX_KV_SHARE of the memory left after the weights."""
    wanted = int(trained * _fraction("ELI_LEGAL_CTX_FRACTION", CTX_FRACTION))
    spare = max(0.0, free_vram_mb + ram_budget_mb - cost.total_mb)
    per_token = cost.kv_mb(1)
    cap = (
        int(spare * _fraction("ELI_LEGAL_CTX_KV_SHARE", CTX_KV_SHARE) / per_token)
        if per_token
        else 0
    )
    return wanted, cap


def _whole(ctx: int) -> int:
    return (ctx // CTX_UNIT) * CTX_UNIT


def _others_on_the_card(hw: Hardware) -> str:
    return hardware.describe_vram_holders(hardware.vram_holders(), total_mb=hw.total_vram_mb)


@dataclass(frozen=True, slots=True)
class LoadPlan:
    """What to ask llama.cpp for, and why."""

    n_ctx: int
    n_gpu_layers: int  # 0: processor only; blocks + 1: every block and the output head
    n_batch: int
    n_threads: int
    blocks: int  # the model's own layer count; 0 when its file could not be read
    experts_in_ram: bool
    free_vram_mb: int
    notes: tuple[str, ...]

    @property
    def on_card(self) -> str:
        """Where the layers go, counted as llama.cpp counts them: the output layer is one."""
        total = self.blocks + 1
        if self.n_gpu_layers <= 0:
            return "processor only"
        if not self.blocks:
            return f"{self.n_gpu_layers} layers on the graphics card"
        if self.n_gpu_layers >= total:
            return f"all {total} layers on the graphics card"
        return f"{self.n_gpu_layers} of {total} layers on the graphics card"

    def describe(self) -> str:
        return f"{self.n_ctx} tokens of context, {self.on_card}"


def plan(
    model_path: str | Path,
    hw: Hardware,
    *,
    gpu_offload: bool,
    want_ctx: int = 0,
    want_layers: int = -1,
    want_threads: int = 0,
    working_ctx: int = 0,
    priority: str = "balanced",
    margin_mb: int = 0,
    expert_offload: bool = False,
) -> LoadPlan:
    """Place this model on this machine as it is now.

    ``want_ctx`` 0 is automatic; a number is the administrator's choice and is reduced only if
    it cannot be held. ``want_layers`` -1 is automatic (as many as fit), 0 keeps the model on
    the processor, a number is a ceiling. ``working_ctx`` is the context the application's own
    steps need: automatic aims for exactly that and puts as many layers on the card as then
    fit; without it, automatic aims for the model's trained context. ``gpu_offload`` is whether the llama.cpp in use can put layers
    on a card at all. ``margin_mb`` is graphics memory to leave free beyond the usual reserve:
    after llama.cpp refuses a plan for lack of memory, the next plan is this one made again,
    from the memory free then, with a wider margin. ``expert_offload`` is whether that
    llama.cpp can be told to keep a mixture-of-experts model's expert tensors in system memory.
    """
    notes: list[str] = []
    fit = _FITS.get(priority, _fit_balanced)
    use_gpu = bool(gpu_offload and hw.has_gpu and hw.free_vram_mb > 0 and want_layers != 0)
    if want_layers != 0 and not use_gpu:
        if hw.has_gpu and not gpu_offload:
            notes.append(
                f"{hw.gpu_name} is present, but the llama.cpp in use has no graphics support: "
                "the model runs on the processor"
            )
        elif hw.uncertain:
            notes.append("a graphics device is present but could not be read: processor only")
    threads = want_threads or recommend_threads(hw, cpu_bound=not use_gpu)
    cost = model_cost(model_path)
    if cost is None:
        # Not readable as GGUF: nothing can be measured, so nothing is assumed. llama.cpp is
        # given the smallest request and reports what is wrong with the file.
        notes.append("the model file's header could not be read: sized as small as possible")
        layers = max(0, want_layers) if use_gpu else 0
        return LoadPlan(
            want_ctx or MIN_CTX, layers, DEFAULT_BATCH, threads, 0, False, 0, tuple(notes)
        )

    trained = gguf_sizes.trained_context(model_path)
    floor_ctx = min(MIN_CTX, _whole(trained)) if trained else MIN_CTX
    floor_ctx = max(CTX_UNIT, floor_ctx)
    ram_budget = cpu_ram_budget_mb(hw)
    free = hw.free_vram_mb if use_gpu else 0
    reserve = vram_reserve_mb(shared=hw.gpu_integrated)
    vram_budget = float(max(0, free - reserve - max(0, margin_mb)))
    if use_gpu and hw.gpu_integrated:
        vram_budget = min(vram_budget, float(ram_budget))

    # A mixture-of-experts model that does not fit whole: every layer's shared weights go to
    # the card and the experts, most of the file and mostly idle per token, stay in memory.
    if (
        use_gpu
        and expert_offload
        and cost.weights.experts_total > 0
        and os.environ.get("ELI_LEGAL_MOE_EXPERTS", "auto").strip().lower() != "card"
        and cost.total_mb + reserve > free
        and hw.available_ram_gb * 1024.0 >= cost.weights.experts_total / MIB * 0.75
    ):
        cost = model_cost(model_path, experts_in_ram=True) or cost
        notes.append(
            f"mixture-of-experts model: the experts ({cost.weights.experts_total / MIB / 1024:.1f} GB) "
            "stay in system memory, everything else is placed on the graphics card"
        )

    user_layers = want_layers if want_layers > 0 else None
    wanted, cap = auto_context_limits(cost, trained, free_vram_mb=free, ram_budget_mb=ram_budget)
    if want_ctx > 0:
        upper = min(want_ctx, trained) if trained else want_ctx
        if upper < want_ctx:
            notes.append(
                f"the model was trained for {trained} tokens of context: {want_ctx} reduced to that"
            )
        first = upper
    else:
        # a measured shortage is a cap of zero (the floor), not "no limit"
        upper = min(wanted, cap) if wanted > 0 else cap
        if working_ctx > 0:
            # What the work needs, and no more: memory the model does not use stays free for
            # the verifier model and for other programs. The share rule does not lower it; the
            # fit below checks real memory and reduces it only if it cannot be held.
            need = -(-working_ctx // CTX_UNIT) * CTX_UNIT  # a need is rounded up
            first = upper = min(need, trained) if trained else need
        else:
            first = upper
    upper, first = max(floor_ctx, _whole(upper)), max(floor_ctx, _whole(first))

    ctx, layers, batch = fit(cost, vram_budget, first, DEFAULT_BATCH, floor_ctx, user_layers)
    ctx, layers, batch = _clamp_to_ram(
        cost, vram_budget, float(ram_budget), ctx, layers, batch, floor_ctx, user_layers
    )
    # Memory left over goes to context, up to what was aimed for.
    while ctx < upper:
        more = min(upper, ctx + _ctx_step(ctx))
        if layers > 0 and needed_mb(cost, more, layers, batch) > vram_budget:
            break
        if cpu_spill_mb(cost, more, layers, batch) > ram_budget:
            break
        ctx = more

    if use_gpu and layers <= 0:
        held = _others_on_the_card(hw)
        notes.append(
            f"{free} MB of graphics memory is free and no layer of this model fits in it"
            + (f"; other programs are using the card: {held}" if held else "")
        )
    elif use_gpu and (layers < _ceiling(cost, user_layers) or ctx < first):
        held = _others_on_the_card(hw)
        if held:
            notes.append(f"other programs are using the card's memory: {held}")
    if ctx < first:
        notes.append(f"context reduced from {first} to {ctx} tokens to fit the memory free now")
    if layers <= 0 and cost.total_mb > ram_budget:
        notes.append(
            f"the model's weights ({cost.total_mb / 1024:.1f} GB) are more than the memory a model "
            f"may take here ({ram_budget / 1024:.1f} GB): it will be read from disk as it runs, slowly"
        )
    return LoadPlan(
        n_ctx=ctx,
        n_gpu_layers=layers,
        n_batch=batch,
        n_threads=threads,
        blocks=cost.blocks,
        experts_in_ram=cost.experts_in_ram and layers > 0,
        free_vram_mb=free,
        notes=tuple(notes),
    )
