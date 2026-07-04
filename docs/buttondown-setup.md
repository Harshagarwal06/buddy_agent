# Buttondown one-time setup

The daily email digest requires a Buttondown account (free up to 100
subscribers, $9/month beyond).

1. Create an account at https://buttondown.com and pick a username
   (e.g. `newsbuddy`). Note it — the signup form on the archive page
   posts to `https://buttondown.com/api/emails/embed-subscribe/<username>`.
2. In Buttondown: Settings → API → copy your API key.
3. In the GitHub repo (https://github.com/harshagarwal06/buddy_agent):
   Settings → Secrets and variables → Actions → New repository secret.
   Add two secrets:
   - `BUTTONDOWN_API_KEY` — the API key from step 2.
   - `BUTTONDOWN_USERNAME` — the username from step 1.
4. Test: subscribe your own address via the form on the archive page,
   confirm the opt-in email, then trigger the workflow manually
   (Actions tab → Daily News Digest → Run workflow) and confirm the
   digest email arrives and the Markdown renders correctly.

If the secrets are absent, the pipeline skips email silently and the
archive page omits the signup form — nothing breaks.
