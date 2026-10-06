.PHONY: clean help install ingest api ui test smoke reset

SHELL=/bin/bash

## Install dependencies with Poetry
install:
	poetry install

## Download the travel DB and build the vector index
ingest:
	python scripts/ingest.py

## Start the backend API on :8000
api:
	python -m customer_support_chat.app.api

## Start the Streamlit UI on :8501
ui:
	streamlit run streamlit_app.py

## Run the test suite (no API key needed)
test:
	python -m pytest

## Run the end-to-end smoke test against a running API (uses the real LLM)
smoke:
	python scripts/smoke_test.py --pause 30

## Undo demo bookings/changes in the travel DB
reset:
	python scripts/reset_demo_data.py

## Remove Python cache files
clean:
	find . -name "__pycache__" -type d -exec rm -r {} \+

## Display help information
help:
	@echo "Available commands:"
	@echo "  make install   - Install dependencies with Poetry"
	@echo "  make ingest    - Download the travel DB and build the vector index"
	@echo "  make api       - Start the backend API on :8000"
	@echo "  make ui        - Start the Streamlit UI on :8501"
	@echo "  make test      - Run the test suite"
	@echo "  make smoke     - End-to-end smoke test against a running API"
	@echo "  make reset     - Undo demo changes in the travel DB"
	@echo "  make clean     - Remove Python cache files"

# Default target
.DEFAULT_GOAL := help
