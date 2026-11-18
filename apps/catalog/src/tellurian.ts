// Importera från Tellurian (#56, CAT-186), without its screens: 1–50 files in Tellurian's format
// at a time, each a draft in a batch of files that the owner reviews and approves as the photos'
// drafts are (BatchPage.tsx). A file that cannot be read is told by itself, and the others go on.
// The same file is never two drafts (CAT-149). ImportPage.tsx shows it.
import { api, TELLURIAN_FILE_MAX_BYTES, TELLURIAN_FILES, TELLURIAN_IMPORT_MAX_BYTES, type TellurianImport } from "./api";

export type FileProblem = "too_many" | "too_large" | "too_large_together";

/** Files chosen: one over 20 MB is left out, and never more than 50, or 60 MB together. */
export function chooseFiles(chosen: File[], files: File[]): { files: File[]; problem: FileProblem | null } {
  let problem: FileProblem | null = null;
  const picked = [...chosen];
  let total = chosen.reduce((sum, file) => sum + file.size, 0);
  for (const file of files) {
    if (file.size > TELLURIAN_FILE_MAX_BYTES) {
      problem = "too_large";
      continue;
    }
    if (picked.length >= TELLURIAN_FILES) {
      problem = "too_many";
      break;
    }
    if (total + file.size > TELLURIAN_IMPORT_MAX_BYTES) {
      problem = "too_large_together";
      break;
    }
    picked.push(file);
    total += file.size;
  }
  return { files: picked, problem };
}

/** How the import went: new drafts, drafts the files already were, and files not read. */
export function importCounts(result: TellurianImport): { made: number; already: number; failed: number } {
  return {
    made: result.files.filter((file) => file.ok && !file.already).length,
    already: result.files.filter((file) => file.ok && file.already).length,
    failed: result.files.filter((file) => !file.ok).length,
  };
}

/** The batch to review and approve: the new drafts', or else the one a file already was in. */
export function reviewBatch(result: TellurianImport | null): string | null {
  return result?.batch?.id ?? result?.files.find((file) => file.ok && file.batch)?.batch ?? null;
}

/** The files, in one request with the import's client-made id: sent again, the same files give
 * the same drafts (CAT-149). */
export async function importFiles(id: string, files: File[]): Promise<{ result: TellurianImport | null; error: unknown }> {
  try {
    return { result: await api.importTellurian({ id }, files), error: null };
  } catch (error) {
    return { result: null, error };
  }
}
