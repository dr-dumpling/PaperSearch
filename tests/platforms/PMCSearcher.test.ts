import axios from 'axios';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { afterEach, describe, expect, it, jest } from '@jest/globals';
import { PMCSearcher } from '../../src/platforms/PMCSearcher.js';

describe('PMCSearcher', () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('resolves publisher PDF URLs through Europe PMC before downloading', async () => {
    const pdf = Buffer.alloc(10_100, 0x20);
    pdf.write('%PDF-1.7\n', 0, 'latin1');
    pdf.write('\n%%EOF\n', pdf.length - 7, 'latin1');
    const get = jest.spyOn(axios, 'get').mockImplementation(async (url: any) => {
      if (String(url).includes('europepmc')) {
        return {
          data: {
            resultList: {
              result: [
                {
                  fullTextUrlList: {
                    fullTextUrl: [
                      {
                        documentStyle: 'pdf',
                        site: 'Unpaywall',
                        url: 'https://publisher.test/article.pdf'
                      }
                    ]
                  }
                }
              ]
            }
          }
        } as any;
      }
      return {
        status: 200,
        headers: {
          'content-type': 'application/pdf',
          'content-length': String(pdf.length)
        },
        data: pdf
      } as any;
    });

    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pmc-download-test-'));
    try {
      const filePath = await new PMCSearcher().downloadPdf('PMC3531190', { savePath: dir });

      expect(filePath).toContain('pmc_PMC3531190.pdf');
      expect(fs.readFileSync(filePath).subarray(0, 5).toString('latin1')).toBe('%PDF-');
      expect(fs.readFileSync(filePath).subarray(-32).toString('latin1')).toContain('%%EOF');
      expect(get).toHaveBeenNthCalledWith(
        1,
        'https://www.ebi.ac.uk/europepmc/webservices/rest/search',
        expect.objectContaining({
          params: expect.objectContaining({ query: 'PMC3531190' })
        })
      );
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
