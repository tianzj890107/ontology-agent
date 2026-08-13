package com.boulderaitech.data.ontology.application.management.crypto;

import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

@Component
public class ConnectionConfigCrypto {

    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int GCM_IV_LENGTH = 12;
    private static final int GCM_TAG_LENGTH = 128;
    private static final int AES_KEY_LENGTH = 32;

    private final SecretKey secretKey;
    private final SecureRandom secureRandom = new SecureRandom();

    public ConnectionConfigCrypto(
            @Value("${ontology.crypto.secret}") String secretBase64) {
        if (secretBase64 == null || secretBase64.isBlank()) {
            throw new IllegalStateException("ontology.crypto.secret must be configured");
        }
        byte[] keyBytes;
        try {
            keyBytes = Base64.getDecoder().decode(secretBase64.trim());
        } catch (IllegalArgumentException ex) {
            throw new IllegalStateException("ontology.crypto.secret must be valid Base64", ex);
        }
        if (keyBytes.length != AES_KEY_LENGTH) {
            throw new IllegalStateException(
                    "ontology.crypto.secret must decode to 32 bytes for AES-256, got " + keyBytes.length);
        }
        this.secretKey = new SecretKeySpec(keyBytes, "AES");
    }

    public String encrypt(String plain) {
        if (plain == null) {
            throw new IllegalArgumentException("plain text must not be null");
        }
        try {
            byte[] iv = new byte[GCM_IV_LENGTH];
            secureRandom.nextBytes(iv);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, secretKey, new GCMParameterSpec(GCM_TAG_LENGTH, iv));
            byte[] cipherText = cipher.doFinal(plain.getBytes(StandardCharsets.UTF_8));

            byte[] combined = new byte[iv.length + cipherText.length];
            System.arraycopy(iv, 0, combined, 0, iv.length);
            System.arraycopy(cipherText, 0, combined, iv.length, cipherText.length);
            return Base64.getEncoder().encodeToString(combined);
        } catch (GeneralSecurityException ex) {
            throw new IllegalStateException("Failed to encrypt connection config password", ex);
        }
    }

    public String decrypt(String cipherBase64) {
        if (cipherBase64 == null || cipherBase64.isBlank()) {
            throw new IllegalArgumentException("cipher text must not be null or blank");
        }
        try {
            byte[] combined = Base64.getDecoder().decode(cipherBase64.trim());
            if (combined.length <= GCM_IV_LENGTH) {
                throw new IllegalArgumentException("Invalid cipher text");
            }

            byte[] iv = Arrays.copyOfRange(combined, 0, GCM_IV_LENGTH);
            byte[] cipherText = Arrays.copyOfRange(combined, GCM_IV_LENGTH, combined.length);

            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, secretKey, new GCMParameterSpec(GCM_TAG_LENGTH, iv));
            byte[] plain = cipher.doFinal(cipherText);
            return new String(plain, StandardCharsets.UTF_8);
        } catch (IllegalArgumentException ex) {
            throw ex;
        } catch (GeneralSecurityException ex) {
            throw new IllegalStateException("Failed to decrypt connection config password", ex);
        }
    }
}
