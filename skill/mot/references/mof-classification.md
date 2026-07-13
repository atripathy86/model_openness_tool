# MOF classification and gap interpretation

MOT evaluates both artifact completeness and licensing. A component counts only when its
artifact is included and its applicable license is open under the active MOT license catalog.
License resolution follows component-specific, content-type global, distribution global,
then unlicensed precedence. MOT separately warns when an open license is not considered
type-appropriate for code, data, or documentation.

Classes are cumulative. Class I is the most demanding; Class III is the entry class. Always
use `mot catalog` as the versioned source of truth because catalogs can change.

## Class III: usable release foundation

Required catalog components:

- Model architecture
- Model parameters (Final)
- Evaluation results
- Model card
- Data card
- Technical report

Sample model outputs are optional. Under current scorer parity behavior, a research paper can
satisfy the technical-report requirement.

Use MOT's missing, invalid, unlicensed, and license warnings to recommend publishing the
architecture definition, final weights, results, and core documentation under applicable open
licenses.

## Class II: code and evaluation reproducibility

Requires Class III plus:

- Training code
- Inference code
- Evaluation code
- Evaluation data

Supporting libraries and tools are optional. Use MOT's linked GitHub inspection to look for
revision-pinned source artifacts and component-scoped repository licenses. A filename match is
evidence for review, not proof that the code fully reproduces the released model.

## Class I: fullest release and reconstruction support

Requires Classes III and II plus:

- Datasets
- Data preprocessing code
- Model parameters (Intermediate)
- Research paper

Model metadata is optional. Use MOT's linked dataset and paper collection to distinguish an
identified or mentioned source from a released, revision-pinned artifact. Dataset provenance,
exact training-corpus identity, preprocessing reconstruction, and license scope commonly
remain human-review items.

## Reading MOT output

- `confirmed`: conservative score from automatically satisfied decisions.
- `evidence_supported_potential`: score if review-required evidence is ultimately accepted;
  it is not a verified class.
- `present`: retrievable artifact evidence matched a deterministic detector.
- `mentioned_only`: text refers to an artifact but does not prove release.
- `unknown`: evidence did not resolve the component.
- `inaccessible`: the source could not be inspected; do not equate this with absence.
- `unlicensed`: no applicable accepted/open license was established.
- `not_type_appropriate`: the license is open but MOT flags its use for that content type.

For a gap analysis, start with the lowest unsatisfied required component in the target class,
then separate release work from licensing work. Recommend concrete actions such as publishing
the pinned artifact, adding its license file and scope statement, releasing the exact dataset
or preprocessing pipeline, or submitting the evidence for human review.
