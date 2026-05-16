#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

QUERY="${1:-${RAG_QUERY:-}}"
LIMIT="${RAG_LIMIT:-30}"

psql_exec() {
  docker compose exec -T postgres psql -U postgres -d eventops "$@"
}

echo "Database: eventops"
echo "Project: $ROOT_DIR"
echo

echo "== Events =="
psql_exec -c "
select id, name, left(coalesce(description, ''), 120) as description, created_at
from events
order by id;
"

echo
echo "== Knowledge links =="
psql_exec -c "
select id,
       event_id,
       title,
       left(url, 90) as url,
       left(coalesce(description, ''), 180) as description,
       tags,
       visibility,
       is_active,
       created_at
from knowledge_base_links
order by id desc
limit $LIMIT;
"

echo
echo "== Document chunk counts by source =="
psql_exec -c "
select coalesce(knowledge_base_link_id::text, 'ticket:' || ticket_id::text, 'orphan') as source_id,
       source_title,
       count(*) as chunks,
       min(created_at) as first_chunk_at,
       max(created_at) as last_chunk_at
from document_chunks
group by coalesce(knowledge_base_link_id::text, 'ticket:' || ticket_id::text, 'orphan'), source_title
order by last_chunk_at desc
limit $LIMIT;
"

echo
echo "== Latest document chunks =="
psql_exec -c "
select id,
       event_id,
       knowledge_base_link_id,
       ticket_id,
       source_title,
       chunk_index,
       left(content, 500) as content_preview,
       chunk_metadata,
       created_at
from document_chunks
order by id desc
limit $LIMIT;
"

if [[ -n "$QUERY" ]]; then
  export QUERY
  echo
  echo "== Keyword search for: $QUERY =="
  psql_exec -v query="$QUERY" -c "
select id,
       knowledge_base_link_id,
       ticket_id,
       source_title,
       chunk_index,
       left(content, 700) as content_preview,
       created_at
from document_chunks
where lower(content) like '%' || lower(:'query') || '%'
   or lower(source_title) like '%' || lower(:'query') || '%'
order by id desc
limit $LIMIT;
"
else
  echo
  echo "No search query provided. Run, for example:"
  echo "  eventops/scripts/db_rag_dump.sh \"регистрация\""
fi
