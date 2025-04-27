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
RUN pip install discord.py
# environment variables to override in runtime
# DATABASE_PATH defaults to "anmeldung.json"
ENV TOKEN=""
ENV DATABASE_PATH="anmeldung.json"

CMD [ "python", "main.py" ]