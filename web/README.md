# HKU Room Booker UI

This UI can run in two ways.

## Recommended: One Shared Static UI

Host `web/public` once as a static site. Everyone can use the same URL.

Each user still needs their own fork of the repo because their `HKU_UID` and `HKU_PIN` stay in their fork's GitHub Actions secrets.

User setup:

1. Fork the repo.
2. In the fork, add repository secrets:
   - `HKU_UID`
   - `HKU_PIN`
3. Create a GitHub token for that fork with permission to run Actions workflows.
4. Open the shared UI.
5. Enter:
   - GitHub owner
   - Fork repo name
   - Branch, usually `main`
   - Workflow, usually `book.yml`
   - GitHub token
6. Submit the booking form.

The token is used in the browser to call GitHub's workflow dispatch API. Do not enter a token on a UI you do not trust.

Static hosting options:

- GitHub Pages: publish the `web/public` folder.
- Cloudflare Pages: deploy `web/public` as the output directory.
- Netlify: deploy `web/public` as a static site.

This is the lowest-friction fork-only model because users do not need to host their own Render service.

## Optional: Private Server UI

You can also run the Node server in this folder. In server mode, the backend owns one GitHub token and dispatches one configured repo.

```bash
cd web
cp .env.example .env
npm start
```

Required environment:

- `GITHUB_OWNER`: GitHub account or org that owns the repo.
- `GITHUB_REPO`: Repository name.
- `GITHUB_REF`: Branch to dispatch, usually `main`.
- `GITHUB_WORKFLOW_FILE`: Workflow filename, usually `book.yml`.
- `GITHUB_TOKEN`: GitHub token with permission to dispatch Actions workflows.
- `APP_ACCESS_TOKEN`: Private password for the UI API. Set this when hosted publicly.

Good server hosting options: Render, Railway, or Fly.io.
