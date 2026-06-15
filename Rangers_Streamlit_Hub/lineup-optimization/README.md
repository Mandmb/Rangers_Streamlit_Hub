# Baseball Lineup Optimizer

This Streamlit app lets you upload a CSV of players and generate an optimized batting lineup using adjustable weights for:

- AVG
- OBP
- SLG
- ISO
- SB

## CSV Format

Your CSV should include a player/name column and these exact stat columns:

```csv
Player,AVG,OBP,SLG,ISO,SB
Player A,.285,.360,.460,.175,12
Player B,.260,.330,.500,.240,3
```

The player column can be named `Player`, `Name`, `Player Name`, `Hitter`, or `Batter`. If none of those exist, the app uses the first column as the player name.

## How to Run on Mac or Windows

1. Install Python 3.10 or newer.
2. Open Terminal or Command Prompt.
3. Go into this folder:

```bash
cd lineup_optimizer_app
```

4. Install the requirements:

```bash
pip install -r requirements.txt
```

5. Run the app:

```bash
streamlit run app.py
```

## Notes

This app uses a scoring model based on normalized player stats, user-selected stat weights, and lineup spot profiles. It is not a full run expectancy simulator, but it is useful for comparing lineup options based on what you value most.
