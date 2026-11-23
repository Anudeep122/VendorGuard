PORT ?= 8000

run:
	uvicorn app.main:app --host 0.0.0.0 --port $(PORT)

seed:
	python -m app.seed

test:
	STAGE_DELAY_MS=0 LLM_PROVIDER=none python -m pytest -q

.PHONY: run seed test
