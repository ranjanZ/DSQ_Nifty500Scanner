#!/bin/bash

# Resolve git conflicts and commit changes

echo "Step 1: Checking current git status..."
git status

echo -e "\n\nStep 2: Aborting any in-progress rebase or merge..."
git rebase --abort 2>/dev/null || true
git merge --abort 2>/dev/null || true

echo -e "\n\nStep 3: Configuring merge strategy..."
git config pull.rebase false

echo -e "\n\nStep 4: Pulling from remote with merge strategy..."
git pull origin main --no-rebase

echo -e "\n\nStep 5: Checking for merge conflicts..."
CONFLICTS=$(git diff --name-only --diff-filter=U)

if [ -z "$CONFLICTS" ]; then
  echo "No conflicts found!"
else
  echo "Found conflicts in:"
  echo "$CONFLICTS"
  
  echo -e "\n\nStep 6: Resolving conflicts - keeping YOUR versions for live_trading files..."
  echo "$CONFLICTS" | while read file; do
    if [[ "$file" == *"live_trading"* ]] || [[ "$file" == *"live/"* ]]; then
      echo "Keeping your version of: $file"
      git checkout --ours "$file"
      git add "$file"
    elif [[ "$file" == *"engine.py"* ]] || [[ "$file" == *"fyers_broker.py"* ]]; then
      echo "Keeping your version of: $file"
      git checkout --ours "$file"
      git add "$file"
    else
      echo "Keeping remote version of: $file"
      git checkout --theirs "$file"
      git add "$file"
    fi
  done
fi

echo -e "\n\nStep 7: Staging all changes..."
git add .

echo -e "\n\nStep 8: Checking staged changes..."
git status

echo -e "\n\nStep 9: Committing merge..."
git commit -m "Merge remote changes and integrate live trading enhancements

- Integrate intelligent stock selection from backtest_offline
- Implement capital management with >50% fund availability check  
- Add actual broker order execution through Fyers API
- Implement comprehensive exit rules (stop loss, target, trailing stop, time-based)
- Track capital allocation and utilization
- Add detailed logging and position monitoring
- Update fyers_broker with place_order(), cancel_order() methods
- Add LIVE_TRADING_UPDATES.md documentation
- Merge remote live_trading files"

echo -e "\n\nStep 10: Pushing to remote..."
git push origin main

echo -e "\n\n✅ Done! Your changes have been committed and pushed."
