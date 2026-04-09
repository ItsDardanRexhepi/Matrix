## Summary

<!-- One or two sentences. What does this PR change and why? -->

## Changes

<!-- Bulleted list of what's actually different. Include touched paths
when it helps reviewers find their way around. -->

-
-
-

## Testing

<!-- Show what you ran. CI will run the suite again, but please give
reviewers a clear local signal. -->

- [ ] `pytest tests/ -v`
- [ ] `flake8 . --select=E9,F63,F7,F82`
- [ ] Manual smoke test (describe below)

```

```

## Risk / rollout

<!-- Schema migrations, breaking API changes, config knobs, anything
that affects the on-call playbook. If this needs an entry in
docs/RUNBOOK.md, link to the section you updated. -->

- Schema migrations added: <!-- yes/no, version number -->
- Config changes required: <!-- yes/no, key path -->
- Backwards compatible: <!-- yes/no -->

## Checklist

- [ ] Tests added or updated for the behaviour change
- [ ] CHANGELOG.md updated under the next version
- [ ] Docs updated if behaviour or config changed
- [ ] No secrets, credentials, or `.env` files committed
