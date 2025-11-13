# Git Setup (Local)

```
cd "$(dirname "$0")"
git init
git config user.name "J K Thomson"
git config user.email "jkeiththomson#gmail.com"
git add .
git commit -m "Initial commit"
```

# Optional: push to GitHub/GitLab

	git remote add origin git@github.com:jkeiththomson/monarch-tools.git
	git branch -M main
	git push -u origin main


```
cd ~/dev
zip -r monarch-tools-upload.zip monarch-tools \
  -x "monarch-tools/.git/*" \
  -x "monarch-tools/.venv/*" \
  -x "monarch-tools/__pycache__/*" \
  -x "monarch-tools/_analysis/*"
```
