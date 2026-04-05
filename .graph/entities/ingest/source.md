# Source

**Domain:** ingest  
**Slug:** `source`

## What it represents

An **upstream catalog root** (e.g. library, provider) from which containers and assets are discovered.

## Lifecycle phase

**Persisted** configuration + discovery scope.

## Owning domain

ingest

## What depends on it

Containers, importers, discovery volume and policy.

## What produces it

Operator configuration / Core persistence.

## What must NOT be assumed

- That a source implies anything about the broadcast grid or playout session.
