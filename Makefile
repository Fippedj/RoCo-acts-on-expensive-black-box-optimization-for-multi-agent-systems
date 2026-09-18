.PHONY: test lint format doctor

test:
	python -m pytest

lint:
	ruff check src tests

format:
	ruff format src tests

doctor:
	python -m roco_ebbo doctor
