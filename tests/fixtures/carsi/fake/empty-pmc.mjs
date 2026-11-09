// The CLI fixture's synthetic DOIs have no repository copy. Never ask a live API.
import { appendFileSync } from 'node:fs';
import http from 'node:http';
import https from 'node:https';

// Searchers use axios, which goes through node:http/https: those fail at once too, so the open stages find
// nothing on any machine instead of waiting on the network.
for (const mod of [http, https]) {
  mod.request = mod.get = (...args) => {
    const target = args.find((arg) => typeof arg === 'string' || arg instanceof URL) || args[0]?.hostname || '';
    throw new Error(`Unexpected request in offline CARSI CLI test: ${target}`);
  };
}

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
