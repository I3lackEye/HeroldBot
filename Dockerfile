FROM python:3.13.2-alpine3.21
LABEL maintainer="deb4sh <github@b4sh.de>"
# update and install deps
RUN pip install --upgrade pip
# install rootless user
RUN adduser -D worker
USER worker
WORKDIR /home/worker
# copy bot and requirements
COPY --chown=worker:worker bot.py bot.py
# copy and install req
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
# copy projektdata
COPY . .
# environment variables to override in runtime
# DATABASE_PATH defaults to "anmeldung.json"
ENV TOKEN=""
ENV DATABASE_PATH="anmeldung.json"

CMD [ "python", "modules/main.py" ]