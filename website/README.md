# Website (same repo)

| Path | Role | Public URL |
|------|------|------------|
| `landing/` | Product HTML site | `https://applejuicy23.github.io/steempeg/` |
| `docs/` + `mkdocs.yml` | MkDocs Material | `https://applejuicy23.github.io/steempeg/docs/` |

Repo-root `docs/` (release notes, ROADMAP, readme screenshots) is **unchanged** — different folder.

## Local preview

```bash
# Landing: open website/landing/index.html after copying assets, or:
cd website
python -m http.server 8080 --directory landing
# then copy logo/media beside landing or adjust paths

# Docs
pip install -r requirements.txt
mkdocs serve -f mkdocs.yml
```

## Deploy

Push to `main` (or run **Pages** workflow manually).  
GitHub → Settings → Pages → Source: **GitHub Actions**.
