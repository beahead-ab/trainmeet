package app.trainmeet.id;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.security.SecureRandom;
import org.junit.jupiter.api.Test;

class CodesTest {
    private final SecureRandom random = new SecureRandom();

    @Test
    void aCodeHasSixDigitsWithLeadingZerosKept() {
        for (int i = 0; i < 1000; i++) {
            assertTrue(Codes.newCode(random).matches("\\d{6}"));
        }
    }

    @Test
    void onlyTheRightCodeMatchesAndTheHashIsSalted() {
        String salt = Codes.newSalt(random);
        String hash = Codes.hash("012345", salt);
        assertTrue(Codes.matches("012345", salt, hash));
        assertTrue(Codes.matches(" 012 345 ", salt, hash));
        assertTrue(Codes.matches("012-345", salt, hash));
        assertFalse(Codes.matches("012346", salt, hash));
        assertFalse(Codes.matches("12345", salt, hash));
        assertFalse(Codes.matches(null, salt, hash));
        assertNotEquals(hash, Codes.hash("012345", Codes.newSalt(random)));
    }

    @Test
    void anAddressIsKeptInSmallLetters() {
        assertEquals("kim@example.com", Codes.normalizeEmail("  Kim@Example.COM "));
        assertNull(Codes.normalizeEmail("kim"));
        assertNull(Codes.normalizeEmail("kim@example"));
        assertNull(Codes.normalizeEmail("kim@@example.com"));
        assertNull(Codes.normalizeEmail(null));
    }

    @Test
    void aNameIsTidiedAndKeptShort() {
        assertEquals("Kim Ek", Codes.normalizeName("  Kim   Ek "));
        assertNull(Codes.normalizeName("   "));
        assertEquals(Codes.NAME_LENGTH, Codes.normalizeName("x".repeat(200)).length());
    }

    @Test
    void theCountPerAddressNeverHoldsTheAddress() {
        String key = Codes.addressKey("kim@example.com");
        assertFalse(key.contains("kim"));
        assertEquals(key, Codes.addressKey("kim@example.com"));
    }
}
