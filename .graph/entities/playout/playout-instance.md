# PlayoutInstance

**Domain:** playout  
**Slug:** `playout-instance`

## What it represents

**AIR’s single active session** context: one running playout engine session with plan handle, format, producers—**one at a time** per engine process model.

## Lifecycle phase

**Runtime** only; exists while AIR is executing for a channel session.

## Owning domain

playout (execution sublayer **inside AIR**); Core holds **supervision** and gRPC, not frame state.

## What depends on it

Decoding, switching, mux, byte emission into attached sink.

## What produces it

AIR engine start/session setup from ChannelManager commands.

## What must NOT be assumed

- That multiple concurrent PlayoutInstances are supported in one engine (not the model).
- That session state is authoritative for historical **as-run** editorial records without Core’s logging pipeline.
