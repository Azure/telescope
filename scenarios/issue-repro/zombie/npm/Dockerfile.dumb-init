ARG CODE_VERSION=20.11.0-alpine3.18

# Production image, copy all the files and run next
FROM node:${CODE_VERSION} AS runner
COPY --chown=node package.json /home/node

USER root
RUN npm install -g npm@10.5.0

# Install dumb-init
RUN apk add --no-cache dumb-init

USER node
WORKDIR /home/node
# RUN chown -R node /home/node
RUN chmod -R 777 /home/node

ENV npm_config_cache=/home/node/app/.npm

RUN rm -rf /home/node/node_modules/.bin/next
RUN rm -rf /home/node/node_modules/.bin/nanoid
RUN npm i next@13.5.6 --force


RUN echo $USER
RUN npm install -ignore-engines --pure-lockfile && npm run build
RUN npm cache clean --force

EXPOSE 3000

# Next.js collects completely anonymous telemetry data about general usage.
# Learn more here: https://nextjs.org/telemetry
# Uncomment the following line in case you want to disable telemetry.
# ENV NEXT_TELEMETRY_DISABLED 1
ENV PORT 3000

# Use dumb-init as the entry point for the container
ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD npm run task && npm start