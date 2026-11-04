// The CLI fixture's synthetic DOIs have no repository copy. Never ask a live API.
import { appendFileSync } from 'node:fs';

globalThis.fetch = async (input) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  const doi = url.searchParams.get('ids') || '';
  if (url.origin !== 'https://pmc.ncbi.nlm.nih.gov'
      || url.pathname !== '/tools/idconv/api/v1/articles/' || !/^10\.1000\//i.test(doi)) {
    throw new Error(`Unexpected fetch in offline CARSI CLI test: ${url.origin}${url.pathname}`);
  }
  if (process.env.PAPER_SEARCH_TEST_PMC_LOG) {
    appendFileSync(process.env.PAPER_SEARCH_TEST_PMC_LOG, `${doi.toLowerCase()}\n`);
  }
  return new Response(JSON.stringify({ records: [] }), {
    status: 200, headers: { 'Content-Type': 'application/json' },
  });
};
