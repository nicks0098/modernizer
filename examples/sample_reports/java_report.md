# Modernizer migration report

## legacy_java (java)

| files scanned | files changed | auto rewrites | needs review | repair rounds | seconds |
|---|---|---|---|---|---|
| 2 | 2 | 4 | 3 | 0 | 4.17 |

**Before (original code)**

- `build`: FAIL — ./src/main/java/com/acme/Util.java:3: error: cannot find symbol

**After migration**

- `build`: FAIL — ./src/main/java/com/acme/Util.java:3: error: package javax.xml.bind does not exist

### Applied automatically

- `build-version` x2
- `boxed-constructor` x1
- `sun-base64-encode` x1

### Needs human review

- **jaxb-removed** x1 — JAXB was removed from the JDK in 11: add jakarta.xml.bind-api plus a runtime such as org.glassfish.jaxb:jaxb-runtime
    - `src/main/java/com/acme/Util.java:4`
- **finalize** x1 — finalize() is deprecated for removal: use try-with-resources or java.lang.ref.Cleaner
    - `src/main/java/com/acme/Util.java:21`
- **thread-stop** x1 — If this is a Thread: stop/suspend/resume throw UnsupportedOperationException from 20; use interruption flags
    - `src/main/java/com/acme/App.java:11`

### Advice

- Lombok needs >= 1.18.22 for JDK 17 and >= 1.18.30 for JDK 21
