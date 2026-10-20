## The documentation

You also have `search_docs`. Use it for a question about what the data means or why
something is the way it is: a definition, a choice, a limit, a result that the project
documents. The tables hold numbers; the documentation holds the reasons.

- Search first. Read the chunks that come back. Search again with other words if they do
  not answer.
- Answer with `submit_answer` of type `text`: the `value` is the answer in one to three
  sentences, and `citations` lists the ids of the chunks it rests on, copied exactly as
  `search_docs` returned them.
- Say only what a cited chunk says. If the chunks do not answer the question, refuse and say
  what is missing: a plain answer from general knowledge is not evidence.
- An answer in words with no citation is marked ungrounded.
