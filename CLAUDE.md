# News Buddy - Claude Instructions

Follow `AGENTS.md` for the repository's shared ground truth, runtime model,
safety rules, known gaps, and documentation contract.

For detailed architecture and operational context, start at
`openwiki/index.md` when it exists. OpenWiki documentation is generated and
reviewable; source code, configuration, tests, and workflows remain
authoritative if documentation and implementation disagree.

Do not describe News Buddy as an active `deepagents` curator. The production
application is a deterministic LangGraph pipeline with model calls for article
summaries and editorial image planning.

<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with
`openwiki/quickstart.md`, then follow its links to architecture, workflows,
domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow proposes wiki updates in a draft
pull request. Review and correct generated claims against source before merge;
when an error is likely to recur, also tighten `openwiki/INSTRUCTIONS.md`.

<!-- OPENWIKI:END -->
