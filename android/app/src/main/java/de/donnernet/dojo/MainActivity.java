package de.donnernet.dojo;

import android.graphics.Color;
import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(DojoUpdaterPlugin.class);
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(Color.parseColor("#0b0a0f"));
        getWindow().setNavigationBarColor(Color.parseColor("#0b0a0f"));
        getWindow().getDecorView().setBackgroundColor(Color.parseColor("#0b0a0f"));
    }
}
