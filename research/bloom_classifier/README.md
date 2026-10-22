# Bloom classifier — offline research

Kaggle notebooks. An SVM baseline, then a BERT fine-tune, predicting the Bloom
level of a question from its text.

This never gates the item bank. Published accuracy for four-level Bloom
classification sits near 59%, which is too low to label questions
automatically. It suggests a label during human review, and it is a chapter in
the FYP document. The live product does not import it.

## Setup

- Needs labelled items, which the question factory produces (M5). Training
  before that means training on nothing.
- Export labelled items as a **private Kaggle Dataset** and read them from
  `/kaggle/input`. A versioned dataset is what makes a run reproducible.
- Secrets through Add-ons -> Secrets, read with `UserSecretsClient`. Assume
  anything written in a cell will end up public.
- GPU and internet are both off by default: Settings -> Accelerator.

## What gets committed here

`metrics.json`, the confusion matrix, and the notebook with outputs cleared.
Not the checkpoint — a fine-tuned BERT is hundreds of megabytes and GitHub
rejects files over 100 MB. Leave weights on Kaggle.
