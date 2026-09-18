# Translation and layout notes

- Source: user-provided selectable-text PDF, 22 pages; extracted with the PDF text layer rather than OCR.
- The paper is an arXiv preprint (arXiv:2512.03762v2). It contains the main paper, appendix, prompts, and generated heuristic examples.
- `paper.md` provides bilingual alignment for the substantive abstract, method, experiment, result, and critical-reading blocks. The code-heavy appendix is represented by source-anchored explanations rather than verbatim reproduction.
- Figures 1–3 and Tables 1–4 were cropped from rendered PDF pages. Crops are approximate semantic crops and exclude surrounding prose where possible.
- Important interpretation note: the paper’s “black-box setting” limits information exposed to the LLM prompt; it is not the same as an expensive black-box objective oracle in Bayesian optimization.
- Appendix prompt templates contain apparent copied/misaligned condition labels around the critic prompts (pp.15–16 in the supplied PDF). Reproduction should audit these templates before implementation.
