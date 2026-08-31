# Internal Server Error Repair

## Symptom

Sending `hi` in Direct mode displayed:

```text
Operation failed: Internal Server Error
```

## Root cause

The browser submitted Direct requests with `verify: true`. After the primary response, the API called the independent reviewer using the raw user message. The reviewer expected a `GoalContract` and evaluated `contract.to_dict()`. A plain string has no `to_dict` method, producing an unhandled `AttributeError` and HTTP 500.

## Corrected flow

1. DPN AI receives the message.
2. Lightweight greetings use a minimal no-tool model request.
3. The response is saved normally.
4. Lightweight conversation does not run an unnecessary reviewer.
5. For substantial Direct requests, DPN AI derives a valid `GoalContract` before review.
6. The reviewer also accepts raw text defensively and converts it internally.
7. Unexpected failures receive an error ID and a local traceback log.

## User-data impact

None. The patch replaces application code and browser assets only. It does not overwrite:

- `.env`
- `data`
- `workspace`
- local model files
- voice files
- user plugins
- project records
- memory
- conversations