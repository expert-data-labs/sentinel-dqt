# 7. Documents in MongoDB: `reviews`

**The situation.** Product reviews are stored as MongoDB documents. A comment is optional, so many documents simply don't have a `comment` field, and the author's country is nested inside an `author` sub-document. You want to know what share of reviews have text, and that the author's country is almost always known.

**You'll learn:** how rules apply to documents without fixed columns, how a missing field is treated, and how to reach into nested documents.

```bash
uv run sentinel validate reviews
```

> `examples.setup` loads 200 reviews into the `reviews` collection of the `sentinel_examples` database. About 20% have no `comment` field at all.

---

## The data

The first two documents (`created_at` is relative to when you ran the setup):

```json
{ "review_id": 1, "product_sku": "SKU-0021", "rating": 2,
  "author": { "name": "user13", "country": "DE" },
  "created_at": "<31 hours ago>",
  "comment": "Great" }

{ "review_id": 2, "product_sku": "SKU-0022", "rating": 2,
  "author": { "name": "user303", "country": "BR" },
  "created_at": "<4 hours ago>" }
```

The second has no `comment` key: not an empty string, not `null`, just absent.

## The dataset and policy

```yaml
source_type: mongodb
config_reference: mongodb://localhost:27017/sentinel_examples?collection=reviews
```

For MongoDB, the URL names the database and the `collection` parameter names the collection. Credentials work as in scenario 6: `mongodb://etl:${MONGO_PASSWORD}@host/db?collection=reviews`. Atlas `mongodb+srv://` URLs work too.

| Rule | Type | Threshold | Note |
|---|---|---|---|
| `row_count` | `row_count` | at least 50 | Counts documents |
| `review_id_unique` | `uniqueness` on `review_id` | no duplicates | |
| `comment_present` | `null_rate` on `comment` | at most 30% | `severity: info` |
| `author_country_known` | `null_rate` on `author.country` | at most 5% | A dotted path into the sub-document |
| `reviews_freshness` | `freshness` on `created_at` | within 1440 minutes (a day) | |

## What you'll see

```text
Dataset: reviews
Run ID:  84ebcef0-d365-4541-83ba-3a007ff32364
Result:  PASS

  ✓ row_count  actual=200  expected: row_count >= 50
  ✓ review_id_unique  actual=0  expected: review_id_unique <= 0
  ✓ comment_present  actual=0.205  expected: comment_present <= 0.3
  ✓ author_country_known  actual=0  expected: author_country_known <= 0.05
  ✓ reviews_freshness  actual=0.01385  expected: reviews_freshness <= 1440
```

- **`comment_present`: 0.205.** 41 of the 200 reviews have no `comment` field, and Sentinel counts a missing field exactly like `null`. That's what you want for documents: "no comment" is the same fact whether the application wrote `null` or left the key out.
- **`author_country_known`: 0.** `author.country` follows the path into each review's `author` sub-document. Every author has a country.
- **Everything else works as on a table.** Rows are documents, uniqueness and freshness work on any field, and every query runs inside MongoDB as an aggregation, so only counts come back.

If you add a `schema` rule to a MongoDB policy, Sentinel infers field types from a random sample of documents (1000 by default). A field seen with two different types is reported as `unknown`. See the [MongoDB notes](../components/data-sources.md#mongodb).

## Try it

Open a shell on the collection:

```bash
docker compose exec mongodb mongosh sentinel_examples
```

- **Remove more comments:** `db.reviews.updateMany({review_id: {$lte: 40}}, {$unset: {comment: ""}})`. `comment_present` rises to `0.355`, above the 30% limit, and fails. It's blocking by default, so add `blocking: false` to the rule if you only want to track it.
- **Lose some countries:** `db.reviews.updateMany({review_id: {$lte: 20}}, {$unset: {"author.country": ""}})`. `author_country_known` fails with `actual=0.1`.

`uv run python -m examples.setup` reloads the original collection.

**Next:** [8. Parquet files and data lakes](08-clickstream-parquet.md)
