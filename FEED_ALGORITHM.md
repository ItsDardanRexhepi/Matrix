# Feed Algorithm — "For You" ranking (v1)

Operator-facing spec for the social-feed ranker. It is **generated from and kept in
lockstep with** [`runtime/social/feed_ranker.py`](runtime/social/feed_ranker.py); a
drift test (`tests/test_feed_algorithm_doc.py`) fails CI if the weight defaults here
stop matching the code.

> **v1 is transparent, weighted, config-tunable scoring.**
> **There is no machine learning and no per-user model anywhere.** The only
> personalization is the viewer's own follow set — a signal they control directly by
> following/unfollowing. Any future "engagement learning" is a separate proposal
> requiring explicit sign-off, not part of this system.

## Where it runs

**Server-side, in the 0pnMatrx platform** — never on the device. The iOS client calls
`GET /api/v1/social/feed/{wallet}?mode=for_you`, which crosses the standard
`_call → gate_action` security seam like every other service, then invokes
`SocialService.get_feed(address, limit, mode)`. **The server ranks; the client
renders.** The client never sees a ranking signal it didn't already have.

Two modes on the same endpoint:

| `mode` | Behavior |
|---|---|
| `latest` (default) | Chronological — posts from followed authors + the viewer's own, newest first. Also the **honest fallback** whenever ranking can't run. Never dressed up as "For You". |
| `for_you` | The transparent weighted ranking described below. |

## Signals (the ONLY inputs)

The ranker reads exactly four already-stored, non-sensitive signals per post,
normalized into a `FeedCandidate(id, author_id, created_at, likes, comments)`:

1. **Recency** — `created_at` (post publish time).
2. **Engagement** — public `likes` count + public `comments` count.
3. **Affinity** — does the viewer follow the author? (boolean, from the viewer's own follow list)
4. **Discovery** — the complement of affinity (the author is not followed).

It reads **nothing else** — no message bodies, no DMs, no private flags, no profile
PII, no watch-time, no cross-user behavioral history. `FeedCandidate` is the ranker's
entire input surface, and a test asserts it exposes only those five fields, so a new
signal cannot be added silently.

## Privacy (absolute, both modes)

`SocialService.get_feed` filters the candidate set to **publicly-visible items only**
(`_is_public_item`) **before** ranking or chronological assembly. Private or
confidential content (any item whose visibility is not `public`) **never becomes a
candidate**, so it structurally cannot enter anyone's feed — not the ranked feed, not
the Latest feed, not even the viewer's own private items. Proof-shares carry an
explicit `visibility`; plain posts have none and are public by default.

## The score

For each public candidate the linear score is a weighted sum of four terms:

```
score =  w_recency    * recency_term
       + w_engagement * engagement_term
       + w_affinity   * (1 if followed else 0)
       + w_discovery  * (1 if not followed else 0)
```

- **recency_term** = `0.5 ** (age_hours / recency_halflife_hours)` — exponential
  half-life decay. Future/zero ages clamp to `1.0` (clock-skew safe).
- **engagement_term** = `min(log1p(likes + comment_weight * comments), engagement_ceiling)`
  — diminishing returns via `log1p`, then **hard-capped** at the ceiling.

Every ranked item carries a `breakdown` of its four term contributions, so any
ordering is fully explainable and can be surfaced for debugging — the ranking is
never fabricated.

## Weights (defaults — all operator-tunable)

Set under the `feed_ranker` key of the social service config
(`SocialService` merges it over `DEFAULT_CONFIG`). Change a number → the feed changes,
explainably, with no retraining.

| Knob | Default | Meaning |
|---|---|---|
| `recency` | `1.0` | weight of the recency term |
| `engagement` | `0.6` | weight of the (capped) engagement term |
| `affinity` | `0.9` | boost for authors the viewer follows |
| `discovery` | `0.4` | weight for non-followed authors' posts |
| `recency_halflife_hours` | `6.0` | a post loses half its recency term every N hours |
| `comment_weight` | `2.0` | a comment counts as this many likes in engagement |
| `engagement_ceiling` | `4.0` | max engagement term — the anti-domination cap |
| `discovery_cap_fraction` | `0.20` | max share of a page from non-followed authors |
| `max_posts_per_author` | `3` | max slots one author may occupy on a page (every mode) |

## Guardrails

- **Engagement ceiling (one viral post can't dominate).** Past the ceiling, more
  likes/comments add **zero** score, so a runaway-viral post can't swamp everything;
  recency and affinity still decide order among high-engagement posts.
- **Discovery hard cap (no flood).** At most `floor(discovery_cap_fraction * page_size)`
  of a page comes from non-followed authors. When followed content can't fill the page,
  the page is **shorter** — it is *never* backfilled with strangers. This is what stops
  a flood of high-engagement non-followed posts from taking over a feed. The excess is
  not destroyed; a larger page / future paginated call surfaces it.
- **Author diversity (no single-account takeover).** A hard cap in *every* mode,
  including cold-start: no single author may occupy more than `max_posts_per_author`
  slots on a page. This stops one account — viral or spamming — from owning a page
  even when there is no follow signal to lean on (a brand-new viewer). It bounds
  per-account dominance; it does **not** solve distinct-account (Sybil) collusion,
  which is an identity-layer concern a ranker cannot fix — an honest limitation, not
  a silent one.
- **Cold-start (new users).** A viewer who follows no one gets an all-discovery feed
  ranked by recency + engagement (the follow-based discovery cap is lifted —
  everything is discovery), still **author-diversity-capped** so no single account
  dominates, and bounded by the requested page size. As they follow people, affinity
  takes over.
- **Honest fallback.** If ranking cannot run (e.g. a misconfigured weight), `get_feed`
  logs and returns the chronological **Latest** feed — it never 500s and never
  fabricates a ranked order or a score.

## Performance

The ranker is O(n log n) over the candidate set (one score pass + one sort), pure
Python, no I/O, no network, no model load — the same order of cost as the chronological
sort it augments. Parity with the Latest feed is expected.

## Live updates

Both modes are served over the same endpoint and the same SSE feed-event stream, so
iOS live-updates work identically whether the user is on **For You** or **Latest** —
a new post triggers a refetch in the active mode.
