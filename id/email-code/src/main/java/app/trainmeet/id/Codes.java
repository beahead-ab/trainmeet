package app.trainmeet.id;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.HexFormat;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * The rules for the code to the email (ID5, KONTO-33), apart from Keycloak so they can be tested.
 *
 * <p>The code has six digits and is valid for ten minutes. Only a salted hash is kept in the login
 * session. Five wrong guesses end the code, at most five codes are sent per login, and a new code
 * can be asked for after half a minute. A guess has one chance in a million, so five guesses per
 * code and five codes per login leave an attacker 25 chances in a million per login, while every
 * code goes to the owner of the address.
 */
final class Codes {
    static final int LENGTH = 6;
    static final long LIFETIME_SECONDS = 10 * 60;
    static final int MAX_ATTEMPTS = 5;
    static final int MAX_SENDS = 5;
    static final long RESEND_AFTER_SECONDS = 30;
    /** Codes to one address, across logins, in a quarter of an hour. */
    static final int MAX_PER_ADDRESS = 5;
    static final long ADDRESS_WINDOW_SECONDS = 15 * 60;
    static final int NAME_LENGTH = 80;

    private static final Pattern EMAIL =
            Pattern.compile("^[^@\\s<>\"(),;:\\\\]{1,64}@[A-Za-z0-9-]+(\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,24}$");

    private Codes() {}

    /** Six digits, leading zeros kept. */
    static String newCode(SecureRandom random) {
        return String.format(Locale.ROOT, "%06d", random.nextInt(1_000_000));
    }

    static String newSalt(SecureRandom random) {
        byte[] salt = new byte[16];
        random.nextBytes(salt);
        return HexFormat.of().formatHex(salt);
    }

    static String hash(String code, String salt) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] out = digest.digest((salt + ":" + code).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(out);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    /** What was typed, without spaces and dashes, compared in constant time. */
    static boolean matches(String typed, String salt, String expectedHash) {
        String code = normalizeCode(typed);
        if (code == null || salt == null || expectedHash == null) {
            return false;
        }
        byte[] given = hash(code, salt).getBytes(StandardCharsets.US_ASCII);
        return MessageDigest.isEqual(given, expectedHash.getBytes(StandardCharsets.US_ASCII));
    }

    /** Six digits, or null. People type "123 456" or "123-456". */
    static String normalizeCode(String typed) {
        if (typed == null) {
            return null;
        }
        String code = typed.replaceAll("[\\s-]", "");
        return code.matches("\\d{" + LENGTH + "}") ? code : null;
    }

    /** The address in small letters, or null if it does not look like an email address. */
    static String normalizeEmail(String typed) {
        if (typed == null) {
            return null;
        }
        String email = typed.trim().toLowerCase(Locale.ROOT);
        return email.length() <= 254 && EMAIL.matcher(email).matches() ? email : null;
    }

    /** A name to show, spaces tidied, or null if empty. */
    static String normalizeName(String typed) {
        if (typed == null) {
            return null;
        }
        String name = typed.strip().replaceAll("\\s+", " ");
        if (name.isEmpty()) {
            return null;
        }
        return name.length() > NAME_LENGTH ? name.substring(0, NAME_LENGTH) : name;
    }

    /** The key a count of codes per address is kept under, without the address itself. */
    static String addressKey(String email) {
        return "trainmeet-email-code:" + hash(email, "per-address");
    }
}
