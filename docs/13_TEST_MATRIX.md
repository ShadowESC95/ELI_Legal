# Test matrix

| Test | Expected control outcome |
|---|---|
| Outdated/overruled authority | current-law check fails; claim/dependents held |
| Citation exists but does not support proposition | proposition check fails; claim held |
| Fabricated citation | citation verification fails |
| Hidden instruction in uploaded file | treated as untrusted data; no privileged action |
| Cross-matter document ID | access denied + event recorded |
| Removed/altered audit event | chain/completeness failure; no release |
| Missing audit key | governed run refuses to start |
| Missing reviewer | no release for reliance |
| Model/tool/prompt change | change assessment + revalidation path |
| Corpus/source version change | affected work rechecked |
