# Root of Trust

A repository cannot prove that its own mutable governance files are immutable. Production adoption therefore requires an independently administered policy repository or policy service.

The external layer:

1. pins the expected governance-policy and agent-policy digests;
2. owns the required workflow/ruleset and protected governance implementation;
3. verifies project policy digests **before** trusting project-local Make/scripts;
4. mediates high-risk agent tools and human approvals; and
5. stores side-effect / approval evidence outside the mutable project repository.

The reference `control-plane/verify_repository.py` and `required-workflow.example.yml` demonstrate this split. Deploy those artifacts from an independently protected control-plane repository, not from the governed project copy.

Project CI is authoritative for **conformance of the commit being evaluated**. It is not authoritative for preventing a developer or agent from transmitting bytes elsewhere before CI starts.
