# Support notes: favorites / follow state wrong (escalated)

Collected by the support team. Times are UTC.

- **Ticket #4812** (first report), from user `maria_k`: "The heart icon is filled on posts I've never liked. Unliking does nothing, then it flips back."
- **Ticket #4815**, from `devon`: "Profile of an author I don't follow says 'Unfollow'."
- **Ticket #4821**, from `priya.writes` (author): "I fixed a typo in my article and it still shows the old text to readers for a minute or so."
- **Ticket #4830**, from `tomasz` (author): "I deleted a post by mistake. My friend could still open it for a bit afterwards."
- Several users say a refresh sometimes "fixes" it, and sometimes makes it worse.
- Nobody has reported it from the mobile app, which talks to the same API but hasn't shipped a release this week.

Support's guess was a frontend caching bug. Engineering hasn't confirmed anything yet.
