#!/usr/bin/env bash

function start_replset() {
    mongosh mongodb://localhost:27017/admin --quiet --eval 'rs.initiate()' --eval 'var cnf = rs.config(); cnf.members[0].host = "mongo-server-0.mongo-server:27017"; rs.reconfig(cnf, {force: true}); printjson(rs.status())'
}

start_replset "$@"