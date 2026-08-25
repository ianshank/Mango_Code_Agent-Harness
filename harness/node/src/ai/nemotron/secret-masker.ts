/**
 * Secret Masker and Sanitization Utility.
 *
 * Requirement Citations:
 * - C-AI-SEC-1: Secret sanitization and prevention of sensitive key leakage in stdout/logs
 * - INV-1: Secret scan covers working tree and full history
 */

export class SecretMasker {
  /**
   * Masks a sensitive API key or token, showing only prefix and suffix.
   * Example: "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"
   * Returns: "nvapi-sSeC...NcWq"
   */
  static mask(secret: string | undefined | null): string {
    if (!secret) return '<UNSET>';
    const trimmed = secret.trim();
    if (trimmed.length <= 10) {
      return '****';
    }
    const prefix = trimmed.slice(0, 10);
    const suffix = trimmed.slice(-4);
    return `${prefix}...${suffix}`;
  }

  /**
   * Redacts any instances of known secrets from a string or error message.
   */
  static sanitize(
    text: string,
    knownSecrets: readonly (string | undefined | null)[],
  ): string {
    if (!text) return '';
    let result = text;
    for (const s of knownSecrets) {
      if (s && s.length >= 8) {
        const masked = SecretMasker.mask(s);
        result = result.split(s).join(masked);
      }
    }
    return result;
  }
}
