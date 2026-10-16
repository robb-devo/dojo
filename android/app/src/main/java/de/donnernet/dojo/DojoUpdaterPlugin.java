package de.donnernet.dojo;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import androidx.core.content.FileProvider;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

@CapacitorPlugin(name = "DojoUpdater")
public class DojoUpdaterPlugin extends Plugin {

    @PluginMethod
    public void getInfo(PluginCall call) {
        try {
            Context c = getContext();
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            JSObject r = new JSObject();
            r.put("versionName", pi.versionName);
            r.put("versionCode", Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode);
            r.put("webBasePath", prefs().getString("serverBasePath", ""));
            call.resolve(r);
        } catch (Exception e) { call.reject(e.getMessage()); }
    }

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences("CapWebViewSettings", Context.MODE_PRIVATE);
    }

    private static void download(String url, File out) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
        con.setInstanceFollowRedirects(true);
        con.setConnectTimeout(15000);
        con.setReadTimeout(60000);
        int code = con.getResponseCode();
        if (code / 100 == 3) { // cross-host redirect (github -> objects.githubusercontent)
            String loc = con.getHeaderField("Location");
            con.disconnect();
            download(loc, out);
            return;
        }
        if (code != 200) throw new Exception("HTTP " + code + " for " + url);
        out.getParentFile().mkdirs();
        try (InputStream in = con.getInputStream(); FileOutputStream fo = new FileOutputStream(out)) {
            byte[] b = new byte[16384];
            int n;
            while ((n = in.read(b)) > 0) fo.write(b, 0, n);
        } finally { con.disconnect(); }
    }

    /** Downloads a web bundle into app storage and activates it on next launch. */
    @PluginMethod
    public void downloadBundle(PluginCall call) {
        String base = call.getString("base");
        String version = call.getString("version");
        JSArray files = call.getArray("files");
        if (base == null || version == null || files == null) { call.reject("missing args"); return; }
        new Thread(() -> {
            try {
                File root = new File(getContext().getFilesDir(), "bundles");
                File tmp = new File(root, version + ".tmp");
                deleteRec(tmp);
                for (int i = 0; i < files.length(); i++) {
                    String f = files.getString(i);
                    if (f.contains("..")) throw new Exception("bad path");
                    download(base + f, new File(tmp, f));
                }
                File dst = new File(root, version);
                deleteRec(dst);
                if (!tmp.renameTo(dst)) throw new Exception("rename failed");
                // Capacitor reads this on startup (and resets it when a new APK is installed).
                prefs().edit().putString("serverBasePath", dst.getAbsolutePath()).apply();
                File[] old = root.listFiles();
                if (old != null) for (File o : old) if (!o.getName().equals(version)) deleteRec(o);
                JSObject r = new JSObject();
                r.put("path", dst.getAbsolutePath());
                call.resolve(r);
            } catch (Exception e) { call.reject(e.getMessage()); }
        }).start();
    }

    /** Revert to the web files bundled in the APK (next launch). */
    @PluginMethod
    public void resetBundle(PluginCall call) {
        prefs().edit().remove("serverBasePath").apply();
        call.resolve();
    }

    @PluginMethod
    public void downloadAndInstall(PluginCall call) {
        String url = call.getString("url");
        if (url == null) { call.reject("missing url"); return; }
        Context c = getContext();
        if (Build.VERSION.SDK_INT >= 26 && !c.getPackageManager().canRequestPackageInstalls()) {
            Intent s = new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + c.getPackageName()));
            s.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            c.startActivity(s);
            call.reject("Allow 'Install unknown apps' for Dojo, then tap Update again");
            return;
        }
        new Thread(() -> {
            try {
                File out = new File(c.getCacheDir(), "update/dojo-update.apk");
                out.delete();
                download(url, out);
                Uri uri = FileProvider.getUriForFile(c, c.getPackageName() + ".fileprovider", out);
                Intent i = new Intent(Intent.ACTION_VIEW);
                i.setDataAndType(uri, "application/vnd.android.package-archive");
                i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
                c.startActivity(i);
                call.resolve();
            } catch (Exception e) { call.reject(e.getMessage()); }
        }).start();
    }

    private static void deleteRec(File f) {
        if (f == null || !f.exists()) return;
        File[] k = f.listFiles();
        if (k != null) for (File x : k) deleteRec(x);
        f.delete();
    }
}
