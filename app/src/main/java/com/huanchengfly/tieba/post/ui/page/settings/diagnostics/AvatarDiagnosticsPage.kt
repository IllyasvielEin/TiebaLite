package com.huanchengfly.tieba.post.ui.page.settings.diagnostics

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.MaterialTheme
import androidx.compose.material.Scaffold
import androidx.compose.material.Switch
import androidx.compose.material.Text
import androidx.compose.material.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import com.huanchengfly.tieba.post.R
import com.huanchengfly.tieba.post.diagnostics.AvatarDiagnostics
import com.huanchengfly.tieba.post.ui.widgets.compose.BackNavigationIcon
import com.huanchengfly.tieba.post.ui.widgets.compose.TitleCentredToolbar
import com.ramcosta.composedestinations.annotation.Destination
import com.ramcosta.composedestinations.navigation.DestinationsNavigator

@Destination
@Composable
fun AvatarDiagnosticsPage(navigator: DestinationsNavigator) {
    val context = LocalContext.current
    val snapshot by AvatarDiagnostics.snapshots.collectAsState()
    Scaffold(
        backgroundColor = Color.Transparent,
        topBar = {
            TitleCentredToolbar(
                title = { Text(stringResource(R.string.title_avatar_diagnostics)) },
                navigationIcon = { BackNavigationIcon(onBackPressed = { navigator.navigateUp() }) },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier.padding(padding).fillMaxSize()
                .verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(stringResource(R.string.avatar_diagnostics_instructions))
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(stringResource(R.string.avatar_diagnostics_enable), modifier = Modifier.weight(1f))
                Switch(
                    checked = snapshot.enabled,
                    onCheckedChange = { AvatarDiagnostics.store.setEnabled(it) },
                )
            }
            Text(
                stringResource(R.string.avatar_diagnostics_privacy),
                style = MaterialTheme.typography.caption,
            )
            Text(
                stringResource(R.string.avatar_diagnostics_coverage),
                style = MaterialTheme.typography.caption,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                TextButton(onClick = { AvatarDiagnostics.store.clear() }) {
                    Text(stringResource(R.string.avatar_diagnostics_clear))
                }
                TextButton(onClick = {
                    // Read at click time, so a just-disabled/cleared session cannot copy stale UI state.
                    val report = AvatarDiagnostics.store.snapshot().report()
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("Avatar diagnostics", report))
                    Toast.makeText(context, R.string.avatar_diagnostics_copied, Toast.LENGTH_SHORT).show()
                }) {
                    Text(stringResource(R.string.avatar_diagnostics_copy))
                }
            }
            Text(
                text = snapshot.report(),
                style = MaterialTheme.typography.caption,
                fontFamily = FontFamily.Monospace,
            )
        }
    }
}
