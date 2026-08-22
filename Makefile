COMPOSE ?= docker-compose

.PHONY: up down logs ps rebuild

up:
	$(COMPOSE) up --build -d

rebuild:
	$(COMPOSE) build --no-cache

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps
