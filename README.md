		# monarch-tools: Python tools for customizing Monarch Money.
		
		Here’s the canonical, up-to-date way to run monarch-tools extract in your current setup.
		
## 1. Activate monarch-tools

- Make sure you’re in the repo, venv is active and editable is installed:
	
	```
	cd ~/dev/mon/monarch-tools
	source .venv/bin/activate
	pip install -e .
	```
- Sanity check (optional)
	
```
python -m monarch_tools hello
``` 

## 2. Run extract
- Run the script that extracts all of the transactions from the bank statement (pdf)

	```
	python -m monarch_tools extract \
	  --pdf statements/chase/9391/2018/20180112-statements-9391.pdf \
	  --out out
	```
	
* What this does:
	* Reads the Chase PDF
	* Writes two files to out/:
		* 20180112-statements-9391.activity.csv (raw activity)
		* 20180112-statements-9391.monarch.csv (Monarch-ready input)
	
* You’ll see output like:

	```
	[chase extractor] Wrote activity CSV with 163 rows: 
		/Users/keith/dev/mon/monarch-tools/out/20180112-statements-9391.activity.csv
	[chase extractor] Payments and credits (count): 4
	[chase extractor] Purchases and fees (count): 159
	[chase extractor] Total Payments and credits: 10123.07
	[chase extractor] Total Purchases and fees: -9995.47
	wrote:
	  monarch: /Users/keith/dev/mon/monarch-tools/out/20180112-statements-9391.monarch.csv
	```

- Confirm the output

	```
	ls -l out/20180112-statements-9391*activity.csv
	ls -l out/20180112-statements-9391*monarch.csv
	```
- You should see both .activity.csv and .monarch.csv.

## 3. Run categorize
- Run the script that does a first pass at assigning categories to transactions and launches interactive mode:

- You need four input files:

	* Transactions CSV (from extract)
	* Categories taxonomy
	* Groups taxonomy
	* Rules file

* For your repo, that’s typically:

	* out/20180112-statements-9391.monarch.csv
	* data/categories.txt
	* data/groups.txt
	* data/rules.json

* Run this command:

	```
	python -m monarch_tools categorize \
	  --in out/20180112-statements-9391.monarch.csv \
	  --categories data/categories.txt \
	  --groups data/groups.txt \
	  --rules data/rules.json
	```
	  
* What happens:
	* Launches the full-screen curses TUI so you can:
		* assign categories
		* edit taxonomy inline
		* update rules
	* On exit:
		* updates data/rules.json
		* updates the CSV in place (unless --out is supplied)

* Optional: write to a new CSV instead of overwriting:

	```
	python -m monarch_tools categorize \
  		--in out/20180112-statements-9391.monarch.csv \
  		--out out/20180112-statements-9391.categorized.csv \
  		--categories data/categories.txt \
  		--groups data/groups.txt \
  		--rules data/rules.json
  ```
  