import path from 'node:path';
import { fileURLToPath } from 'node:url';
export const PROJECT_ROOT = fileURLToPath(new URL('../../../../', import.meta.url));
export const DEFAULT_DB = path.join(PROJECT_ROOT, 'data', 'gmaps-reviews.db');
