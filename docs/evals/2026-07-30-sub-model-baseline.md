# Sub-Model Baseline Evaluation

**Fixtures captured:** 2026-07-30T16:35:17+00:00
**Word target:** 70–110 words per summary

Scored with the pipeline's own `RubricMiddleware` and `_article_brief_errors`. Brief validity is the headline metric: an invalid brief blocks publication under `images.require_all`.

## Results

| Model | Brief valid | First-pass rubric | Strict recovery | JSON fail | p50 | p95 | Mean total tok | Words in range |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| meta/llama-3.1-8b-instruct _(baseline)_ | 96% | 42% | 23% | 0 | 2.1s | 3.3s | 1373 | 17% |
| nvidia/nemotron-3-super-120b-a12b | 0% | 0% | n/a | 24 | 6.2s | 35.3s | 0 | 0% |
| poolside/laguna-xs-2.1 | 88% | 88% | n/a | 0 | 2.6s | 4.3s | 1362 | 83% |
| mistralai/mistral-medium-3.5-128b | 67% | 21% | 55% | 0 | 86.7s | 184.2s | 1000 | 4% |
| google/gemma-4-31b-it | 67% | 38% | 86% | 0 | 25.1s | 108.1s | 1040 | 21% |

## Failure breakdown

**meta/llama-3.1-8b-instruct**
- `short image_labels`: 1
- JSON parse failures (inferred from all four image fields missing at once): 0

**nvidia/nemotron-3-super-120b-a12b**
- `image_alt`: 24
- `image_labels`: 24
- `image_layout`: 24
- `image_prompt`: 24
- JSON parse failures (inferred from all four image fields missing at once): 24
  - a response truncated at the token cap is also invalid JSON, so these may be truncation rather than formatting failures

**poolside/laguna-xs-2.1**
- `short image_labels`: 3
- JSON parse failures (inferred from all four image fields missing at once): 0

**mistralai/mistral-medium-3.5-128b**
- `short image_labels`: 2
- JSON parse failures (inferred from all four image fields missing at once): 0

**google/gemma-4-31b-it**
- `short image_labels`: 5
- JSON parse failures (inferred from all four image fields missing at once): 0

## Sample outputs

### meta/llama-3.1-8b-instruct

**Mark Zuckerberg is planning a big push into personal AI agents**

Mark Zuckerberg plans a big push into personal AI agents that can work 24/7 on users' behalf to help achieve goals and improve life. The first domain agents have taken off in is coding, but engineers are more technical and willing to spend time making them work. Meta aims to differentiate its vision from companies like Anthropic and OpenAI, but faces an uphill battle due to its AI efforts lagging behind and general distrust toward the company.

**Microsoft is openly competing with OpenAI, Anthropic more than ever**

Microsoft openly competes with OpenAI and Anthropic by selling its own AI models and agents, promising lower costs and greater control for enterprises. This move is driven by Microsoft's unique position as a cloud provider and software-as-a-service company, as well as its stakes in the two biggest AI labs. By keeping its models separate from the harness, Microsoft aims to give enterprises the flexibility to swap models and avoid relying on a single vendor.

**OpenAI president says it&#8217;s &#8216;building a family of devices&#8217; for its AI chatbots**

OpenAI is building a family of devices for interacting with its AI models, with president Greg Brockman predicting a shift to voice-based interactions for the vast majority of tasks. The devices are still in development, with no release date confirmed, and will allow users to talk to their computers instead of typing. OpenAI is also working to address trust issues with its AI models, including developing solutions to offer verifiable guarantees about user data privacy.

### nvidia/nemotron-3-super-120b-a12b

**Mark Zuckerberg is planning a big push into personal AI agents**

_failed: summarizer returned an incomplete article image brief: image_prompt, image_layout, image_labels, image_alt_

**Microsoft is openly competing with OpenAI, Anthropic more than ever**

_failed: summarizer returned an incomplete article image brief: image_prompt, image_layout, image_labels, image_alt_

**OpenAI president says it&#8217;s &#8216;building a family of devices&#8217; for its AI chatbots**

_failed: summarizer returned an incomplete article image brief: image_prompt, image_layout, image_labels, image_alt_

### poolside/laguna-xs-2.1

**Mark Zuckerberg is planning a big push into personal AI agents**

Meta CEO Mark Zuckerberg announced plans for a major push into personal AI agents that can work 24/7 on behalf of users to improve life areas like health, relationships, and finances. The company aims to make these agents consumer-friendly products that work out of the box, differentiating from current coding-focused agents by Anthropic and OpenAI. Meta faces challenges including lagging AI capabilities compared to Google and Microsoft, limited ecosystem access to personal data, and existing trust issues with users regarding its smart glasses.

**Microsoft is openly competing with OpenAI, Anthropic more than ever**

Microsoft is aggressively competing with OpenAI and Anthropic by promoting its own AI models and agents as alternatives to the frontier labs' services. With $90 billion in quarterly revenue and $331.8 billion for the fiscal year, Microsoft leverages its Azure cloud platform and stakes in OpenAI and Anthropic while warning enterprises that relying on external AI providers risks data leaks and vendor lock-in. CEO Satya Nadella is positioning Microsoft's homegrown Copilot agents and AI infrastructure as a more secure, cost-effective option that keeps customer data and relationships in-house.

**OpenAI president says it&#8217;s &#8216;building a family of devices&#8217; for its AI chatbots**

OpenAI president Greg Brockman confirmed the company is developing a 'family of devices' to interact with its AI models, though he did not specify what form these devices will take or provide a release timeline. He envisions a future where people will speak to computers rather than type for most tasks, and OpenAI is also working on technical solutions to address trust concerns around private data in its AI systems. The devices represent OpenAI's expansion beyond software into hardware as it competes with tech giants like Apple, while navigating ongoing legal challenges.

### mistralai/mistral-medium-3.5-128b

**Mark Zuckerberg is planning a big push into personal AI agents**

_failed: The read operation timed out_

**Microsoft is openly competing with OpenAI, Anthropic more than ever**

Microsoft is now directly competing with OpenAI and Anthropic by offering its own AI models, agents, and security tools to enterprises. CEO Satya Nadella argues companies should avoid dependency on single AI labs, citing risks like data leaks and vendor lock-in, and instead use swappable models with Microsoft’s platforms. This shift positions Microsoft as a self-sufficient alternative, leveraging its $331.8 billion annual revenue and cloud dominance to capture more AI spending.

**OpenAI president says it&#8217;s &#8216;building a family of devices&#8217; for its AI chatbots**

OpenAI is developing a family of hardware devices to enable voice-based interactions with its AI chatbots. President Greg Brockman predicts most computer tasks will shift from typing to speaking, citing emerging solutions like soundproof masks for open-office use. The move aims to redefine human-computer interaction while addressing privacy and trust through auditable AI data guarantees.

### google/gemma-4-31b-it

**Mark Zuckerberg is planning a big push into personal AI agents**

Meta is developing personal AI agents designed to perform tasks and manage goals, and improve daily life on behalf of users. Mark Zuckerberg aims to differentiate these tools from enterprise-focused coding agents by creating a consumer-ready product that requires no technical expertise for billions of people to adopt. This strategic shift intends to establish a new foundation for the company's future product ecosystem and revenue streams.

**Microsoft is openly competing with OpenAI, Anthropic more than ever**

Microsoft is positioning itself as a direct competitor to its AI partners OpenAI and Anthropic by urging enterprises to decouple their AI applications from specific model providers. CEO Satya Nadella argues that relying on a single frontier lab for agentic infrastructure risks data leaks and vendor lock-in, advocating instead for a swappable model architecture. This strategic shift allows Microsoft to sell its own homegrown models and security tools while maintaining control over the customer relationship through its Copilot agent layer.

**OpenAI president says it&#8217;s &#8216;building a family of devices&#8217; for its AI chatbots**

OpenAI is developing a family of hardware devices designed specifically for interacting with its AI chatbots. President Greg Brockman indicates these devices aim to shift the primary user interface from typing to voice-based communication for most computing tasks. This move signals a strategic effort to move AI beyond software applications into dedicated physical hardware to change how users engage with digital assistants.


## Verdict

**Keep `meta/llama-3.1-8b-instruct`. No candidate passes the criteria fixed
before these results were seen.**

Corpus: 24 articles (target was 25; the archive held 24 usable). Differences
under roughly 10 percentage points are not decisive at this sample size.

### Applying the criteria

1. **Must: brief validity at least equal to baseline (96%), and zero JSON
   failures.** Every candidate fails this gate.
   - `nvidia/nemotron-3-super-120b-a12b` — 0% valid, 24/24 JSON failures.
   - `poolside/laguna-xs-2.1` — 88%, below the 96% baseline.
   - `mistralai/mistral-medium-3.5-128b` — 67%.
   - `google/gemma-4-31b-it` — 67%.

Criterion 1 eliminates the field, so criteria 2–4 never come into play. The
incumbent stays.

### The result that complicates that answer

`poolside/laguna-xs-2.1` is a markedly better summarizer than the incumbent on
every quality measure the harness records:

| | baseline | laguna-xs-2.1 |
| --- | --- | --- |
| First-pass rubric | 42% | **88%** |
| Words in 70–110 target | 17% | **83%** |
| p50 latency | 2.1s | 2.6s |

The baseline passes brief validity while missing the prompt's own word target on
83% of articles, and needing a strict retry on 58% of them — retries that cost
a second model call in production.

Laguna's only failures are three `short image_labels`: labels exceeding 18
characters or 3 words. That is a constraint violation, not a capability gap, and
it is plausibly promptable. The sample outputs point the same way — laguna cites
concrete figures ($90bn quarterly revenue, named executives) where the baseline
stays general.

This is exactly the situation the pre-fixed criteria exist for. The disciplined
answer is that laguna does not pass the gate today, so nothing changes now.

### Recommended follow-up (not done here)

Re-run laguna-xs-2.1 with the `image_labels` length constraint restated more
forcefully in `prompts/summarizer.md`. If its brief validity reaches parity with
the baseline, it becomes the clear winner on criterion 2 by a wide margin. That
is a prompt experiment, and it needs its own before/after comparison.

### Two caveats about reading this table

- **`nvidia/nemotron-3-super-120b-a12b` shows mean total tokens of 0. That is a
  harness artifact, not a measurement.** `failure_result` records no token
  count, so when all 24 articles fail the mean is necessarily 0. It says nothing
  about the model's consumption.
- Its 24 JSON failures cannot be attributed between malformed output and
  truncation at the 512-token cap. The harness documents this ambiguity by
  design: `_summarize_one` collapses both into one `ValueError`. Given the
  budget must hold a 70–110 word summary *and* a full image brief, truncation is
  a live hypothesis.

### Measurement note

Run with `--rpm 30` rather than the configured 8. The rate limiter's
`acquire(blocking=True)` sits inside the timed window in
`_NvidiaChatModel.invoke`, so at 8 RPM every latency figure would have been
dominated by a 7.5s throttle wait rather than model speed. Latency here reflects
the models; production latency at 8 RPM will be higher.
