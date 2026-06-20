package com.example.agrinex

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.webkit.*
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.*
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import com.example.agrinex.theme.*
import com.example.agrinex.R
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {

    private var filePathCallback: ValueCallback<Array<Uri>>? = null
    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        val resultCode = result.resultCode
        val intent = result.data
        if (filePathCallback != null) {
            val results = if (intent == null || resultCode != RESULT_OK) {
                null
            } else {
                val dataString = intent.dataString
                val clipData = intent.clipData
                if (clipData != null) {
                    val count = clipData.itemCount
                    val uris = Array(count) { i -> clipData.getItemAt(i).uri }
                    uris
                } else if (dataString != null) {
                    arrayOf(Uri.parse(dataString))
                } else {
                    null
                }
            }
            filePathCallback!!.onReceiveValue(results)
            filePathCallback = null
        }
    }

    private var geolocationRequestOrigin: String? = null
    private var geolocationCallback: GeolocationPermissions.Callback? = null
    private val locationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val fineGranted = permissions[Manifest.permission.ACCESS_FINE_LOCATION] ?: false
        val coarseGranted = permissions[Manifest.permission.ACCESS_COARSE_LOCATION] ?: false
        if (fineGranted || coarseGranted) {
            geolocationCallback?.invoke(geolocationRequestOrigin, true, false)
        } else {
            geolocationCallback?.invoke(geolocationRequestOrigin, false, false)
        }
        geolocationCallback = null
        geolocationRequestOrigin = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AgriNexTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background
                ) {
                    AppContent(
                        onOpenFileChooser = { callback, params ->
                            filePathCallback = callback
                            val intent = params.createIntent()
                            try {
                                fileChooserLauncher.launch(intent)
                            } catch (e: Exception) {
                                filePathCallback?.onReceiveValue(null)
                                filePathCallback = null
                                Toast.makeText(this, "Cannot open file chooser", Toast.LENGTH_SHORT).show()
                            }
                        },
                        onRequestGeolocation = { origin, callback ->
                            geolocationRequestOrigin = origin
                            geolocationCallback = callback
                            locationPermissionLauncher.launch(
                                arrayOf(
                                    Manifest.permission.ACCESS_FINE_LOCATION,
                                    Manifest.permission.ACCESS_COARSE_LOCATION
                                )
                            )
                        }
                    )
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun AppContent(
    onOpenFileChooser: (ValueCallback<Array<Uri>>, WebChromeClient.FileChooserParams) -> Unit,
    onRequestGeolocation: (String, GeolocationPermissions.Callback) -> Unit
) {
    val context = LocalContext.current
    val sharedPrefs = remember { context.getSharedPreferences("AgriNexPrefs", Context.MODE_PRIVATE) }
    
    val defaultProductionUrl = "https://agrinex-platform.onrender.com"
    var savedUrl by remember { 
        val currentSaved = sharedPrefs.getString("server_url", "") ?: ""
        val url = if (currentSaved.isEmpty()) {
            sharedPrefs.edit().putString("server_url", defaultProductionUrl).apply()
            defaultProductionUrl
        } else {
            currentSaved
        }
        mutableStateOf(url)
    }
    var currentScreen by remember { mutableStateOf("splash") }
    var webViewRef by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    var canGoForward by remember { mutableStateOf(false) }
    var showMenu by remember { mutableStateOf(false) }
    var isPageLoading by remember { mutableStateOf(false) }
    var pageError by remember { mutableStateOf<String?>(null) }
    var inputUrl by remember { mutableStateOf(savedUrl) }

    Box(modifier = Modifier.fillMaxSize()) {
        Crossfade(targetState = currentScreen, label = "ScreenTransition") { screen ->
            when (screen) {
                "splash" -> {
                    SplashScreen(
                        onAnimationFinished = {
                            if (savedUrl.isNotEmpty()) {
                                currentScreen = "webview"
                            } else {
                                currentScreen = "setup"
                            }
                        }
                    )
                }
                "setup" -> {
                    SetupScreen(
                        initialUrl = inputUrl,
                        onLaunch = { url ->
                            val formattedUrl = formatUrl(url)
                            sharedPrefs.edit().putString("server_url", formattedUrl).apply()
                            savedUrl = formattedUrl
                            inputUrl = formattedUrl
                            pageError = null
                            currentScreen = "webview"
                        }
                    )
                }
                "webview" -> {
                    Column(modifier = Modifier.fillMaxSize()) {
                        // Native Forest Green status bar spacer to blend system bar icons
                        Spacer(
                            modifier = Modifier
                                .fillMaxWidth()
                                .windowInsetsTopHeight(WindowInsets.statusBars)
                                .background(ForestGreenPrimary)
                        )
                        
                        Box(modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .navigationBarsPadding()
                        ) {
                            // Back handler for physical system back navigation inside WebView
                            BackHandler(enabled = canGoBack) {
                                webViewRef?.goBack()
                            }

                            if (pageError != null) {
                                ErrorScreen(
                                    error = pageError ?: "Unknown Error",
                                    url = savedUrl,
                                    onRetry = {
                                        pageError = null
                                        webViewRef?.loadUrl(savedUrl)
                                    },
                                    onChangeUrl = {
                                        currentScreen = "setup"
                                    }
                                )
                            } else {
                                AndroidView(
                                    factory = { ctx ->
                                        WebView(ctx).apply {
                                            layoutParams = android.view.ViewGroup.LayoutParams(
                                                android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                                                android.view.ViewGroup.LayoutParams.MATCH_PARENT
                                            )
                                            settings.apply {
                                                javaScriptEnabled = true
                                                domStorageEnabled = true
                                                databaseEnabled = true
                                                allowFileAccess = true
                                                allowContentAccess = true
                                                setGeolocationEnabled(true)
                                                setSupportZoom(true)
                                                builtInZoomControls = true
                                                displayZoomControls = false
                                                userAgentString = "$userAgentString AgriNexAndroidWebView"
                                            }
                                            webViewClient = object : WebViewClient() {
                                                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                                                    super.onPageStarted(view, url, favicon)
                                                    isPageLoading = true
                                                }

                                                override fun onPageFinished(view: WebView?, url: String?) {
                                                    super.onPageFinished(view, url)
                                                    isPageLoading = false
                                                    if (view != null) {
                                                        canGoBack = view.canGoBack()
                                                        canGoForward = view.canGoForward()
                                                    }
                                                }

                                                override fun onReceivedError(
                                                    view: WebView?,
                                                    request: WebResourceRequest?,
                                                    error: WebResourceError?
                                                ) {
                                                    super.onReceivedError(view, request, error)
                                                    if (request?.isForMainFrame == true) {
                                                        pageError = error?.description?.toString() ?: "Cannot connect to server"
                                                        isPageLoading = false
                                                    }
                                                }
                                            }
                                            webChromeClient = object : WebChromeClient() {
                                                override fun onShowFileChooser(
                                                    webView: WebView?,
                                                    filePathCallback: ValueCallback<Array<Uri>>?,
                                                    fileChooserParams: FileChooserParams?
                                                ): Boolean {
                                                    if (filePathCallback != null && fileChooserParams != null) {
                                                        onOpenFileChooser(filePathCallback, fileChooserParams)
                                                        return true
                                                    }
                                                    return false
                                                }

                                                override fun onGeolocationPermissionsShowPrompt(
                                                    origin: String?,
                                                    callback: GeolocationPermissions.Callback?
                                                ) {
                                                    if (origin != null && callback != null) {
                                                        onRequestGeolocation(origin, callback)
                                                    }
                                                }
                                            }
                                            webViewRef = this
                                            loadUrl(savedUrl)
                                        }
                                    },
                                    modifier = Modifier.fillMaxSize()
                                )
                            }

                            // Progress indicator
                            if (isPageLoading && pageError == null) {
                                LinearProgressIndicator(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .height(3.dp)
                                        .align(Alignment.TopCenter),
                                    color = ForestGreenSecondary,
                                    trackColor = Color.Transparent
                                )
                            }

                            // Floating Menu Container
                            Box(
                                modifier = Modifier
                                    .align(Alignment.BottomEnd)
                                    .padding(24.dp)
                            ) {
                                FloatingMenu(
                                    expanded = showMenu,
                                    canGoBack = canGoBack,
                                    canGoForward = canGoForward,
                                    onToggle = { showMenu = !showMenu },
                                    onGoBack = {
                                        webViewRef?.goBack()
                                        showMenu = false
                                    },
                                    onGoForward = {
                                        webViewRef?.goForward()
                                        showMenu = false
                                    },
                                    onRefresh = {
                                        pageError = null
                                        webViewRef?.reload()
                                        showMenu = false
                                    },
                                    onSettings = {
                                        showMenu = false
                                        currentScreen = "setup"
                                    },
                                    onExit = {
                                        (context as? android.app.Activity)?.finish()
                                    }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun SplashScreen(onAnimationFinished: () -> Unit) {
    val alpha = remember { Animatable(0f) }
    val scale = remember { Animatable(0.85f) }

    LaunchedEffect(Unit) {
        launch {
            alpha.animateTo(
                targetValue = 1f,
                animationSpec = tween(durationMillis = 1200, easing = LinearOutSlowInEasing)
            )
        }
        launch {
            scale.animateTo(
                targetValue = 1.0f,
                animationSpec = tween(durationMillis = 1200, easing = LinearOutSlowInEasing)
            )
        }
        kotlinx.coroutines.delay(1800)
        onAnimationFinished()
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(ForestGreenDark, ForestGreenPrimary)
                )
            ),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.graphicsLayer(
                alpha = alpha.value,
                scaleX = scale.value,
                scaleY = scale.value
            )
        ) {
            // Elegant wrapper container for the official branding logo
            Box(
                modifier = Modifier
                    .fillMaxWidth(0.65f)
                    .aspectRatio(1.8f)
                    .clip(RoundedCornerShape(24.dp))
                    .background(Color.White.copy(alpha = 0.08f))
                    .border(1.5.dp, AgriNexGold.copy(alpha = 0.5f), RoundedCornerShape(24.dp))
                    .padding(16.dp),
                contentAlignment = Alignment.Center
            ) {
                Image(
                    painter = painterResource(id = R.drawable.agrinex_logo),
                    contentDescription = "AgriNex Logo",
                    modifier = Modifier.fillMaxSize()
                )
            }
            Spacer(modifier = Modifier.height(28.dp))
            Text(
                text = "AgriNex",
                color = Color.White,
                fontSize = 38.sp,
                fontWeight = FontWeight.Bold,
                letterSpacing = 2.sp
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "GeoAI Agricultural Platform",
                color = ForestGreenLight.copy(alpha = 0.85f),
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 1.sp
            )
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                text = "Where Agriculture Meets AI and GIS",
                color = AgriNexGold.copy(alpha = 0.8f),
                fontSize = 13.sp,
                fontWeight = FontWeight.Light,
                letterSpacing = 0.5.sp
            )
        }
    }
}

@Composable
fun SetupScreen(
    initialUrl: String,
    onLaunch: (String) -> Unit
) {
    var urlText by remember { mutableStateOf(initialUrl) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SoftBackground)
            .statusBarsPadding()
            .navigationBarsPadding(),
        contentAlignment = Alignment.Center
    ) {
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            shape = RoundedCornerShape(28.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 6.dp)
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "Server Configuration",
                    color = ForestGreenPrimary,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "Connect this device to the platform host:",
                    color = Color.Gray,
                    fontSize = 14.sp,
                    textAlign = TextAlign.Center
                )
                Spacer(modifier = Modifier.height(28.dp))
                
                OutlinedTextField(
                    value = urlText,
                    onValueChange = { urlText = it },
                    label = { Text("Server URL / Host IP") },
                    placeholder = { Text("e.g. 192.168.1.100:5000") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth()
                )

                Spacer(modifier = Modifier.height(20.dp))

                Text(
                    text = "Default Presets:",
                    color = Color.DarkGray,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.align(Alignment.Start)
                )
                Spacer(modifier = Modifier.height(8.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Button(
                        onClick = { urlText = "http://10.0.2.2:5000" },
                        colors = ButtonDefaults.buttonColors(containerColor = ForestGreenLight, contentColor = ForestGreenDark),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).padding(end = 4.dp)
                    ) {
                        Text("Emulator", fontSize = 11.sp, maxLines = 1)
                    }

                    Button(
                        onClick = { urlText = "http://192.168.1.100:5000" },
                        colors = ButtonDefaults.buttonColors(containerColor = ForestGreenLight, contentColor = ForestGreenDark),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).padding(horizontal = 4.dp)
                    ) {
                        Text("Local IP", fontSize = 11.sp, maxLines = 1)
                    }

                    Button(
                        onClick = { urlText = "https://agrinex-platform.onrender.com" },
                        colors = ButtonDefaults.buttonColors(containerColor = ForestGreenLight, contentColor = ForestGreenDark),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                        modifier = Modifier.weight(1f).padding(start = 4.dp)
                    ) {
                        Text("Public", fontSize = 11.sp, maxLines = 1)
                    }
                }

                Spacer(modifier = Modifier.height(36.dp))

                Button(
                    onClick = { onLaunch(urlText) },
                    colors = ButtonDefaults.buttonColors(containerColor = ForestGreenPrimary),
                    shape = RoundedCornerShape(16.dp),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp)
                ) {
                    Text(
                        text = "Connect & Launch",
                        color = Color.White,
                        fontSize = 16.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
            }
        }
    }
}

@Composable
fun ErrorScreen(
    error: String,
    url: String,
    onRetry: () -> Unit,
    onChangeUrl: () -> Unit
) {
    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(SoftBackground)
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Box(
                modifier = Modifier
                    .size(80.dp)
                    .clip(CircleShape)
                    .background(Color(0xFFFFECEF)),
                contentAlignment = Alignment.Center
            ) {
                Icon(
                    imageVector = Icons.Default.Close,
                    contentDescription = "Error icon",
                    tint = Color.Red,
                    modifier = Modifier.size(44.dp)
                )
            }
            Spacer(modifier = Modifier.height(24.dp))
            Text(
                text = "Connection Failed",
                color = Color.Black,
                fontSize = 22.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "Could not connect to:\n$url\n\nError: $error",
                color = Color.Gray,
                fontSize = 14.sp,
                textAlign = TextAlign.Center
            )
            Spacer(modifier = Modifier.height(36.dp))

            Button(
                onClick = onRetry,
                colors = ButtonDefaults.buttonColors(containerColor = ForestGreenPrimary),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                Text("Retry Connection", color = Color.White, fontWeight = FontWeight.Bold)
            }

            Spacer(modifier = Modifier.height(12.dp))

            OutlinedButton(
                onClick = onChangeUrl,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                Text("Change Server URL", color = ForestGreenPrimary, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
fun FloatingMenu(
    expanded: Boolean,
    canGoBack: Boolean,
    canGoForward: Boolean,
    onToggle: () -> Unit,
    onGoBack: () -> Unit,
    onGoForward: () -> Unit,
    onRefresh: () -> Unit,
    onSettings: () -> Unit,
    onExit: () -> Unit
) {
    Column(
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        if (expanded) {
            FloatingMenuActionItem(
                icon = Icons.Default.Close,
                label = "Exit App",
                tint = Color.Red,
                onClick = onExit
            )

            FloatingMenuActionItem(
                icon = Icons.Default.Settings,
                label = "Change URL",
                onClick = onSettings
            )

            FloatingMenuActionItem(
                icon = Icons.Default.Refresh,
                label = "Refresh",
                onClick = onRefresh
            )

            if (canGoForward) {
                FloatingMenuActionItem(
                    icon = Icons.Default.ArrowForward,
                    label = "Forward",
                    onClick = onGoForward
                )
            }

            if (canGoBack) {
                FloatingMenuActionItem(
                    icon = Icons.Default.ArrowBack,
                    label = "Back",
                    onClick = onGoBack
                )
            }
        }

        FloatingActionButton(
            onClick = onToggle,
            containerColor = ForestGreenPrimary,
            contentColor = Color.White,
            shape = CircleShape
        ) {
            Icon(
                imageVector = if (expanded) Icons.Default.Close else Icons.Default.Menu,
                contentDescription = "Menu Toggle"
            )
        }
    }
}

@Composable
fun FloatingMenuActionItem(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    label: String,
    tint: Color = ForestGreenPrimary,
    onClick: () -> Unit
) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.End
    ) {
        Card(
            shape = RoundedCornerShape(8.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
            modifier = Modifier.padding(end = 8.dp)
        ) {
            Text(
                text = label,
                color = Color.DarkGray,
                fontSize = 12.sp,
                fontWeight = FontWeight.Medium,
                modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp)
            )
        }

        SmallFloatingActionButton(
            onClick = onClick,
            containerColor = Color.White,
            contentColor = tint,
            shape = CircleShape
        ) {
            Icon(imageVector = icon, contentDescription = label, modifier = Modifier.size(18.dp))
        }
    }
}

fun formatUrl(url: String): String {
    var formatted = url.trim()
    if (formatted.isEmpty()) return ""
    if (!formatted.startsWith("http://") && !formatted.startsWith("https://")) {
        formatted = "http://$formatted"
    }
    if (formatted.endsWith("/")) {
        formatted = formatted.substring(0, formatted.length - 1)
    }
    return formatted
}
