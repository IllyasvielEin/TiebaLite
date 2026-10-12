package com.huanchengfly.tieba.post.activities;

import android.os.Bundle;

import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;

import com.huanchengfly.tieba.post.R;
import com.huanchengfly.tieba.post.utils.TiebaUtil;

/** Launcher shortcuts need an exported entry point, but launch alone must not change account state. */
public class OKSignActivity extends AppCompatActivity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(R.string.title_oksign)
                .setMessage(R.string.message_confirm_shortcut_oksign)
                .setPositiveButton(android.R.string.ok, (ignored, which) -> {
                    TiebaUtil.startSign(this);
                    finish();
                })
                .setNegativeButton(android.R.string.cancel, (ignored, which) -> finish())
                .setOnCancelListener(ignored -> finish())
                .create();
        dialog.show();
        // Reject touches obscured by another app's overlay on this account-changing confirmation.
        dialog.getButton(AlertDialog.BUTTON_POSITIVE).setFilterTouchesWhenObscured(true);
    }
}
