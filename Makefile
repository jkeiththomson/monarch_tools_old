# Makefile for monarch-tools pipeline
# Usage examples:
#   make all
#   make all PDF=statements/chase/9391/2018/20180112-statements-9391.pdf ACCOUNT="Chase Visa 9391"
#   make all-pdfs STATEMENTS_DIR=statements/chase/9391 ACCOUNT="Chase Visa 9391"

PYTHON ?= python
CLI    ?= $(PYTHON) -m monarch_tools

# Defaults – override on the command line as needed.
ACCOUNT      ?= Chase Visa 9391
TYPE         ?= chase
PDF          ?= statements/chase/9391/2018/20180112-statements-9391.pdf
OUT_DIR      ?= out
DATA_DIR     ?= data
STATEMENTS_DIR ?= statements/chase/9391

# Derive stem from the single PDF name
STMT_NAME  := $(notdir $(PDF))
STMT_STEM  := $(basename $(STMT_NAME))

ACTIVITY   := $(OUT_DIR)/$(STMT_STEM).activity.csv
MONARCH    := $(OUT_DIR)/$(STMT_STEM).monarch.csv

# For multi-PDF processing
PDFS       ?= $(wildcard $(STATEMENTS_DIR)/*.pdf)
STEMS      := $(basename $(notdir $(PDFS)))
ACTIVITIES := $(addprefix $(OUT_DIR)/,$(addsuffix .activity.csv,$(STEMS)))
MONARCHS   := $(addprefix $(OUT_DIR)/,$(addsuffix .monarch.csv,$(STEMS)))

.PHONY: all activity categorize categorize-dry monarch sanity clean all-pdfs

# Full pipeline for the single PDF specified by $(PDF)
all: activity categorize monarch sanity

activity:
	@mkdir -p "$(OUT_DIR)"
	$(CLI) activity "$(TYPE)" "$(PDF)" --out-dir "$(OUT_DIR)"

categorize: activity
	$(CLI) categorize \
	  "$(DATA_DIR)/categories.txt" \
	  "$(DATA_DIR)/groups.txt" \
	  "$(DATA_DIR)/rules.json" \
	  "$(ACTIVITY)"

categorize-dry: activity
	$(CLI) categorize \
	  "$(DATA_DIR)/categories.txt" \
	  "$(DATA_DIR)/groups.txt" \
	  "$(DATA_DIR)/rules.json" \
	  "$(ACTIVITY)" \
	  --dry-run

monarch: categorize
	$(CLI) monarch "$(ACCOUNT)" "$(DATA_DIR)/rules.json" "$(ACTIVITY)" --out "$(MONARCH)"

sanity: monarch
	$(CLI) sanity "$(ACTIVITY)" "$(MONARCH)"

# Batch pipeline: run activity->categorize->monarch->sanity for every PDF in STATEMENTS_DIR
all-pdfs: $(MONARCHS)

$(OUT_DIR)/%.activity.csv: $(STATEMENTS_DIR)/%.pdf
	@mkdir -p "$(OUT_DIR)"
	$(CLI) activity "$(TYPE)" "$<" --out-dir "$(OUT_DIR)"

$(OUT_DIR)/%.monarch.csv: $(OUT_DIR)/%.activity.csv
	$(CLI) categorize "$(DATA_DIR)/categories.txt" "$(DATA_DIR)/groups.txt" "$(DATA_DIR)/rules.json" "$<"
	$(CLI) monarch "$(ACCOUNT)" "$(DATA_DIR)/rules.json" "$<" --out "$@"
	$(CLI) sanity "$<" "$@"

clean:
	rm -f "$(ACTIVITY)" "$(MONARCH)"
