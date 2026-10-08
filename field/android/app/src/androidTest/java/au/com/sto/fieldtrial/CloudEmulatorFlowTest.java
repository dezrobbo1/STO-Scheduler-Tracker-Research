package au.com.sto.fieldtrial;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertTrue;

import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.SystemClock;
import android.webkit.WebView;

import androidx.test.core.app.ActivityScenario;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Predicate;

/**
 * Cloud-only PL5 field shakeout. This drives the real Capacitor WebView and
 * native SQLite store on an emulator. It is not genuine-device evidence.
 */
@RunWith(AndroidJUnit4.class)
public class CloudEmulatorFlowTest {

    private ActivityScenario<MainActivity> scenario;
    private WebView webView;

    @Before
    public void setUp() throws Exception {
        scenario = ActivityScenario.launch(MainActivity.class);
        AtomicReference<WebView> reference = new AtomicReference<>();
        scenario.onActivity(activity -> reference.set(activity.getBridge().getWebView()));
        webView = reference.get();
        assertNotNull("Capacitor WebView is unavailable", webView);
        waitFor("document.readyState === 'complete' && !!document.getElementById('signin')", 30_000);
    }

    @After
    public void tearDown() {
        if (scenario != null) {
            scenario.close();
        }
    }

    private String argument(String name) {
        String value = InstrumentationRegistry.getArguments().getString(name);
        assertNotNull("missing instrumentation argument " + name, value);
        return value;
    }

    private String evaluateRaw(String script) throws Exception {
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        InstrumentationRegistry.getInstrumentation().runOnMainSync(() ->
            webView.evaluateJavascript(script, value -> {
                result.set(value);
                latch.countDown();
            })
        );
        assertTrue("JavaScript evaluation timed out: " + script,
            latch.await(10, TimeUnit.SECONDS));
        return result.get();
    }

    private String evaluateString(String script) throws Exception {
        String raw = evaluateRaw(script);
        if ("null".equals(raw)) {
            return null;
        }
        return new JSONArray("[" + raw + "]").getString(0);
    }

    private boolean evaluateBoolean(String script) throws Exception {
        return "true".equals(evaluateRaw(script));
    }

    private void waitFor(String predicate, long timeoutMs) throws Exception {
        long deadline = SystemClock.elapsedRealtime() + timeoutMs;
        while (SystemClock.elapsedRealtime() < deadline) {
            if (evaluateBoolean(predicate)) {
                return;
            }
            SystemClock.sleep(200);
        }
        throw new AssertionError("condition timed out: " + predicate);
    }

    private void waitForField() throws Exception {
        waitFor("!!document.getElementById('field') && !document.getElementById('field').hidden", 30_000);
    }

    private void assertClearedError(JSONObject row) {
        Object value = row.opt("error_code");
        assertTrue("expected cleared local error but found " + value,
            value == null || value == JSONObject.NULL || "".equals(value));
    }

    private JSONObject evidence() throws Exception {
        evaluateRaw(
            "document.getElementById('trial-evidence-output').value='';" +
            "document.getElementById('trial-evidence').click(); true;"
        );
        waitFor("document.getElementById('trial-evidence-output').value.length > 0", 10_000);
        return new JSONObject(evaluateString(
            "document.getElementById('trial-evidence-output').value"
        ));
    }

    private JSONObject waitForEvidence(Predicate<JSONObject> predicate, long timeoutMs)
        throws Exception {
        long deadline = SystemClock.elapsedRealtime() + timeoutMs;
        JSONObject latest = null;
        while (SystemClock.elapsedRealtime() < deadline) {
            latest = evidence();
            if (predicate.test(latest)) {
                return latest;
            }
            SystemClock.sleep(300);
        }
        throw new AssertionError("local evidence did not converge: " +
            (latest == null ? "<none>" : latest.toString()));
    }

    private File evidenceDirectory() {
        Context target = InstrumentationRegistry.getInstrumentation().getTargetContext();
        File directory = new File(target.getExternalFilesDir(null), "cloud-emulator");
        assertTrue("could not create evidence directory",
            directory.exists() || directory.mkdirs());
        return directory;
    }

    private void writeEvidence(String name, JSONObject payload) throws Exception {
        try (OutputStreamWriter writer = new OutputStreamWriter(
            new FileOutputStream(new File(evidenceDirectory(), name + ".json")),
            StandardCharsets.UTF_8)) {
            writer.write(payload.toString(2));
            writer.write("\n");
        }
    }

    private void screenshot(String name) throws Exception {
        Bitmap bitmap = InstrumentationRegistry.getInstrumentation()
            .getUiAutomation().takeScreenshot();
        assertNotNull("screenshot unavailable", bitmap);
        try (FileOutputStream output = new FileOutputStream(
            new File(evidenceDirectory(), name + ".png"))) {
            assertTrue("screenshot compression failed",
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, output));
        } finally {
            bitmap.recycle();
        }
    }

    private void connect(String server, String project, String credential) throws Exception {
        waitFor("!document.getElementById('signin').hidden", 20_000);
        String script =
            "document.getElementById('server').value=" + JSONObject.quote(server) + ";" +
            "document.getElementById('project').value=" + JSONObject.quote(project) + ";" +
            "document.getElementById('token').value=" + JSONObject.quote(credential) + ";" +
            "document.querySelector('#connect-form button').click(); true;";
        evaluateRaw(script);
        try {
            waitForField();
        } catch (AssertionError error) {
            String notice = evaluateString("document.getElementById('notice').textContent");
            String signedIn = evaluateRaw("document.getElementById('signin').hidden");
            throw new AssertionError(
                "field did not open; notice=" + notice + ", signin.hidden=" + signedIn,
                error
            );
        }
        waitFor("document.getElementById('activity').options.length >= 3", 30_000);
    }

    private void launchDeepLink(String project, String activity) {
        Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        Intent intent = new Intent(
            Intent.ACTION_VIEW,
            Uri.parse("sto-field://project/" + project + "/activity/" + activity),
            context,
            MainActivity.class
        );
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        context.startActivity(intent);
    }

    private String selectedActivity() throws Exception {
        return evaluateString("document.getElementById('activity').value");
    }

    private void selectDifferentActivity(String target) throws Exception {
        waitFor(
            "document.getElementById('activity').options.length >= 2 && " +
            "[...document.getElementById('activity').options].some(o => o.value===" +
            JSONObject.quote(target) + ")",
            20_000
        );
        String selected = evaluateString(
            "(() => {" +
            " const s=document.getElementById('activity');" +
            " const other=[...s.options].find(o => o.value !== " + JSONObject.quote(target) + ");" +
            " if (!other) return '';" +
            " s.value=other.value; return s.value;" +
            "})()"
        );
        assertNotNull(selected);
        assertFalse("no alternate activity was available", selected.isEmpty());
        assertNotEquals(target, selected);
    }

    @Test
    public void connectAndCache() throws Exception {
        String project = argument("stoProject");
        String actor = argument("stoActor");
        connect(argument("stoServer"), project, argument("stoCredential"));
        JSONObject current = waitForEvidence(
            value -> project.equals(value.optString("project_id")) &&
                actor.equals(value.optString("actor_user_id")) &&
                value.optInt("cursor", -1) == 0 &&
                argument("stoBaselineHash").equals(value.optString("canonical_hash")),
            30_000
        );
        writeEvidence("01-connected", current);
        screenshot("01-connected");
    }

    @Test
    public void queueWhileBackendUnavailable() throws Exception {
        String activity = argument("stoActivity");
        waitForField();
        evaluateRaw(
            "document.getElementById('activity').value=" + JSONObject.quote(activity) + ";" +
            "document.getElementById('actual-start').value='2026-01-05T09:00';" +
            "document.getElementById('remaining').value='1';" +
            "document.querySelector('#execution button').click(); true;"
        );
        waitForEvidence(value -> {
            JSONArray rows = value.optJSONArray("execution");
            return rows != null && rows.length() == 1 &&
                "queued".equals(rows.optJSONObject(0).optString("local_final_state"));
        }, 20_000);

        evaluateRaw(
            "document.getElementById('activity').value=" + JSONObject.quote(activity) + ";" +
            "document.getElementById('message-text').value='CI emulator offline note';" +
            "document.querySelector('#message button').click(); true;"
        );
        JSONObject current = waitForEvidence(value -> {
            JSONArray executions = value.optJSONArray("execution");
            JSONArray messages = value.optJSONArray("communication");
            return executions != null && executions.length() == 1 &&
                messages != null && messages.length() == 1 &&
                "queued".equals(executions.optJSONObject(0).optString("local_final_state")) &&
                "queued".equals(messages.optJSONObject(0).optString("local_final_state"));
        }, 20_000);
        writeEvidence("02-offline-queued", current);
        screenshot("02-offline-queued");
    }

    @Test
    public void reopenWhileBackendUnavailable() throws Exception {
        String activity = argument("stoActivity");
        waitForField();
        JSONObject current = waitForEvidence(value -> {
            JSONArray executions = value.optJSONArray("execution");
            JSONArray messages = value.optJSONArray("communication");
            return executions != null && executions.length() == 1 &&
                messages != null && messages.length() == 1 &&
                activity.equals(executions.optJSONObject(0).optString("activity_uid")) &&
                "queued".equals(executions.optJSONObject(0).optString("local_final_state")) &&
                "queued".equals(messages.optJSONObject(0).optString("local_final_state"));
        }, 20_000);
        writeEvidence("03-offline-reopen", current);
        screenshot("03-offline-reopen");
    }

    @Test
    public void reconnectAndReconcile() throws Exception {
        waitForField();
        JSONObject current = waitForEvidence(value -> {
            JSONArray executions = value.optJSONArray("execution");
            JSONArray messages = value.optJSONArray("communication");
            return executions != null && executions.length() == 1 &&
                messages != null && messages.length() == 1 &&
                "applied".equals(executions.optJSONObject(0).optString("local_final_state")) &&
                "accepted".equals(messages.optJSONObject(0).optString("local_final_state")) &&
                value.optInt("cursor", -1) >= 2;
        }, 45_000);
        assertClearedError(current.getJSONArray("execution").getJSONObject(0));
        assertClearedError(current.getJSONArray("communication").getJSONObject(0));
        writeEvidence("04-reconciled", current);
        screenshot("04-reconciled");
    }

    @Test
    public void logoutAndConnectB() throws Exception {
        waitForField();
        evaluateRaw("document.getElementById('logout').click(); true;");
        waitFor("!document.getElementById('signin').hidden", 20_000);

        String project = argument("stoProject");
        String actor = argument("stoActor");
        connect(argument("stoServer"), project, argument("stoCredential"));
        JSONObject current = waitForEvidence(value ->
            project.equals(value.optString("project_id")) &&
                actor.equals(value.optString("actor_user_id")) &&
                value.optInt("cursor", -1) >= 2,
            30_000
        );
        assertEquals(0, current.getJSONArray("execution").length());
        assertEquals(0, current.getJSONArray("communication").length());
        writeEvidence("05-account-b", current);
        screenshot("05-account-b");
    }

    @Test
    public void onlineDeepLinkSelectsTarget() throws Exception {
        waitForField();
        String project = argument("stoProject");
        String target = argument("stoActivity");
        selectDifferentActivity(target);
        launchDeepLink(project, target);
        waitFor(
            "document.getElementById('activity').value===" + JSONObject.quote(target),
            20_000
        );
        assertEquals(target, selectedActivity());
        writeEvidence("06-online-deep-link",
            new JSONObject().put("project_id", project).put("selected_activity", target));
        screenshot("06-online-deep-link");
    }

    @Test
    public void offlineDeepLinkRecovers() throws Exception {
        waitForField();
        String project = argument("stoProject");
        String target = argument("stoActivity");
        selectDifferentActivity(target);
        launchDeepLink(project, target);
        SystemClock.sleep(1500);
        assertNotEquals("offline hint was applied before a confirmed sync",
            target, selectedActivity());

        waitFor(
            "document.getElementById('activity').value===" + JSONObject.quote(target),
            35_000
        );
        assertEquals(target, selectedActivity());
        writeEvidence("07-offline-deep-link-recovered",
            new JSONObject().put("project_id", project).put("selected_activity", target));
        screenshot("07-offline-deep-link-recovered");
    }
}
