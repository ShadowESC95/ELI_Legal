class EliV3Adapter:
    """Future composition root for ELI v3 services. Not implemented in the standalone scaffold."""

    def __init__(
        self,
        *,
        inference=None,
        retrieval=None,
        documents=None,
        workflow=None,
        audit=None,
        models=None,
    ):
        self.inference = inference
        self.retrieval = retrieval
        self.documents = documents
        self.workflow = workflow
        self.audit = audit
        self.models = models
