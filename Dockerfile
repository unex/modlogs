FROM python:3.11-alpine

COPY . /app
WORKDIR /app

EXPOSE 8000

RUN pip install pipenv
RUN pipenv install --system --deploy

RUN pip cache purge
RUN pipenv --clear

CMD ["pipenv", "run", "prod"]
