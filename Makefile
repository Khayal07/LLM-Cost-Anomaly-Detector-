.PHONY: up down logs build test sim eval fmt

up:            ## Start the full stack (db + api + dashboard)
	docker-compose up --build

down:          ## Stop the stack and remove containers
	docker-compose down

logs:
	docker-compose logs -f

build:
	docker-compose build

test:          ## Run the test suite
	pytest -q

sim:           ## Generate synthetic traffic against a running API
	python -m simulation.generator --send

eval:          ## Run the detection eval and write eval/report.{md,json}
	python -m simulation.run_eval
