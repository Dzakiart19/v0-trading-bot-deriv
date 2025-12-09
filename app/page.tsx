"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Bot,
  TrendingUp,
  Target,
  Zap,
  Grid3X3,
  LineChart,
  LogIn,
  ExternalLink,
  Shield,
  Wallet,
  Play,
  Square,
} from "lucide-react"

const DERIV_APP_ID = process.env.NEXT_PUBLIC_DERIV_APP_ID || "1089"
const DERIV_OAUTH_URL = `https://oauth.deriv.com/oauth2/authorize?app_id=${DERIV_APP_ID}`

interface DerivAccount {
  loginid: string
  balance: number
  currency: string
  is_virtual: number
}

export default function HomePage() {
  const router = useRouter()
  const [isLoggedIn, setIsLoggedIn] = useState(false)
  const [accounts, setAccounts] = useState<DerivAccount[]>([])
  const [selectedAccount, setSelectedAccount] = useState<DerivAccount | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null)
  const [isAutoRunning, setIsAutoRunning] = useState(false)

  const connectWithToken = useCallback(async (token: string) => {
    setIsLoading(true)
    try {
      const ws = new WebSocket(`wss://ws.derivws.com/websockets/v3?app_id=${DERIV_APP_ID}`)

      ws.onopen = () => {
        ws.send(JSON.stringify({ authorize: token }))
      }

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data)
        if (data.authorize) {
          setIsLoggedIn(true)
          setSelectedAccount({
            loginid: data.authorize.loginid,
            balance: data.authorize.balance,
            currency: data.authorize.currency,
            is_virtual: data.authorize.is_virtual,
          })
          ws.send(JSON.stringify({ balance: 1, account: "all" }))
        }

        if (data.balance && data.balance.accounts) {
          const accts = Object.entries(data.balance.accounts).map(([id, acc]: [string, any]) => ({
            loginid: id,
            balance: acc.balance,
            currency: acc.currency,
            is_virtual: acc.is_virtual ? 1 : 0,
          }))
          setAccounts(accts)
        }

        if (data.error) {
          console.error("Deriv error:", data.error)
          localStorage.removeItem("deriv_token")
          setIsLoggedIn(false)
        }

        setIsLoading(false)
        ws.close()
      }

      ws.onerror = () => {
        setIsLoading(false)
        setIsLoggedIn(false)
      }
    } catch (error) {
      setIsLoading(false)
      setIsLoggedIn(false)
    }
  }, [])

  // Check URL params for Telegram WebApp data
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const strategy = params.get("strategy")
    const token = params.get("token")

    if (strategy) {
      setSelectedStrategy(strategy)
      localStorage.setItem("selected_strategy", strategy)
    }

    if (token) {
      localStorage.setItem("deriv_token", token)
      connectWithToken(token)
    } else {
      const savedToken = localStorage.getItem("deriv_token")
      if (savedToken) {
        connectWithToken(savedToken)
      } else {
        setIsLoading(false)
      }
    }
  }, [connectWithToken])

  // Handle OAuth callback
  useEffect(() => {
    const hash = window.location.hash
    if (hash.includes("token")) {
      const params = new URLSearchParams(hash.replace("#", ""))
      const tokens: string[] = []
      const loginIds: string[] = []

      params.forEach((value, key) => {
        if (key.startsWith("token")) {
          tokens.push(value)
        }
        if (key.startsWith("acct")) {
          loginIds.push(value)
        }
      })

      if (tokens.length > 0) {
        localStorage.setItem("deriv_token", tokens[0])
        localStorage.setItem("deriv_tokens", JSON.stringify(tokens))
        localStorage.setItem("deriv_accounts", JSON.stringify(loginIds))
        connectWithToken(tokens[0])
        window.history.replaceState({}, document.title, window.location.pathname)
      }
    }
  }, [connectWithToken])

  const handleLogin = () => {
    window.location.href = DERIV_OAUTH_URL
  }

  const handleLogout = () => {
    localStorage.removeItem("deriv_token")
    localStorage.removeItem("deriv_tokens")
    localStorage.removeItem("deriv_accounts")
    setIsLoggedIn(false)
    setSelectedAccount(null)
    setAccounts([])
    setIsAutoRunning(false)
  }

  const strategies = [
    {
      id: "terminal",
      name: "Terminal",
      description: "Smart Analysis dengan 80% probability - Multi indicator auto trading",
      icon: LineChart,
      color: "bg-blue-500",
      features: ["RSI + EMA + MACD", "Auto Entry", "Martingale"],
    },
    {
      id: "tick-picker",
      name: "Tick Picker",
      description: "Pattern analysis otomatis untuk Rise/Fall prediction",
      icon: TrendingUp,
      color: "bg-green-500",
      features: ["Tick Pattern", "Auto Trend", "Quick Trade"],
    },
    {
      id: "digitpad",
      name: "DigitPad",
      description: "Digit frequency heatmap auto trading untuk Digit contracts",
      icon: Grid3X3,
      color: "bg-purple-500",
      features: ["Frequency Map", "Hot/Cold Auto", "Even/Odd"],
    },
    {
      id: "amt",
      name: "AMT Accumulator",
      description: "Auto growth rate tracking untuk Accumulator contracts",
      icon: Zap,
      color: "bg-orange-500",
      features: ["Growth Track", "Auto Cashout", "Risk Control"],
    },
    {
      id: "sniper",
      name: "Sniper",
      description: "High probability only - minimum 85% confidence auto execute",
      icon: Target,
      color: "bg-red-500",
      features: ["85%+ Only", "Auto Execute", "Low Risk"],
    },
  ]

  const openStrategy = (strategyId: string) => {
    if (!isLoggedIn) {
      alert("Silakan login ke Deriv terlebih dahulu")
      return
    }
    setSelectedStrategy(strategyId)
    localStorage.setItem("selected_strategy", strategyId)
    router.push(`/${strategyId}?auto=true`)
  }

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0d1117] flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-gray-400">Connecting to Deriv...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-[#0d1117] text-white">
      {/* Header */}
      <header className="border-b border-gray-800 bg-[#161b22]">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Bot className="h-8 w-8 text-blue-500" />
            <div>
              <h1 className="text-xl font-bold">Deriv Auto Trading Bot</h1>
              <p className="text-xs text-gray-400">100% Automatic - User Only Stop</p>
            </div>
          </div>

          {isLoggedIn && selectedAccount ? (
            <div className="flex items-center gap-4">
              <div className="text-right">
                <div className="flex items-center gap-2">
                  <Wallet className="h-4 w-4 text-gray-400" />
                  <span className="font-semibold">
                    {selectedAccount.balance.toFixed(2)} {selectedAccount.currency}
                  </span>
                  {selectedAccount.is_virtual === 1 && <Badge className="bg-yellow-600 text-white text-xs">Demo</Badge>}
                </div>
                <p className="text-xs text-gray-400">{selectedAccount.loginid}</p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleLogout}
                className="border-gray-700 text-gray-300 hover:bg-gray-800 bg-transparent"
              >
                Logout
              </Button>
            </div>
          ) : (
            <Button onClick={handleLogin} className="gap-2 bg-blue-600 hover:bg-blue-700">
              <LogIn className="h-4 w-4" />
              Login Deriv
            </Button>
          )}
        </div>
      </header>

      <main className="container mx-auto px-4 py-8">
        {/* Login Prompt */}
        {!isLoggedIn && (
          <Card className="mb-8 border-blue-500/50 bg-blue-500/10 border">
            <CardContent className="py-6">
              <div className="flex items-center gap-4">
                <Shield className="h-12 w-12 text-blue-500" />
                <div className="flex-1">
                  <h2 className="text-lg font-semibold text-white">Login ke Deriv untuk Memulai</h2>
                  <p className="text-sm text-gray-400">
                    Hubungkan akun Deriv Anda untuk mengakses auto trading 100% otomatis
                  </p>
                </div>
                <Button onClick={handleLogin} size="lg" className="gap-2 bg-blue-600 hover:bg-blue-700">
                  <ExternalLink className="h-4 w-4" />
                  Login dengan Deriv
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Account Selector */}
        {isLoggedIn && accounts.length > 1 && (
          <Card className="mb-8 bg-[#161b22] border-gray-800">
            <CardHeader>
              <CardTitle className="text-lg text-white">Pilih Akun</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {accounts.map((acc) => (
                  <Button
                    key={acc.loginid}
                    variant={selectedAccount?.loginid === acc.loginid ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSelectedAccount(acc)}
                    className={`gap-2 ${selectedAccount?.loginid === acc.loginid ? "bg-blue-600" : "border-gray-700 text-gray-300 hover:bg-gray-800"}`}
                  >
                    {acc.loginid}
                    <Badge className={acc.is_virtual ? "bg-yellow-600" : "bg-green-600"}>
                      {acc.balance.toFixed(2)} {acc.currency}
                    </Badge>
                  </Button>
                ))}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Auto Trading Status */}
        {isLoggedIn && isAutoRunning && (
          <Card className="mb-6 border-green-500/50 bg-green-500/10 border">
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="h-3 w-3 bg-green-500 rounded-full animate-pulse"></div>
                  <span className="font-semibold text-green-400">Auto Trading Active</span>
                </div>
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setIsAutoRunning(false)}
                  className="bg-red-600 hover:bg-red-700"
                >
                  <Square className="h-4 w-4 mr-2" />
                  STOP ALL
                </Button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Strategies Grid */}
        <div className="mb-6">
          <h2 className="text-2xl font-bold mb-2 text-white">Pilih Strategi Auto Trading</h2>
          <p className="text-gray-400">Klik strategi untuk memulai trading otomatis - Anda hanya perlu STOP</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {strategies.map((strategy) => {
            const Icon = strategy.icon
            const isSelected = selectedStrategy === strategy.id

            return (
              <Card
                key={strategy.id}
                className={`cursor-pointer transition-all hover:scale-[1.02] bg-[#161b22] border-gray-800 hover:border-gray-600 ${
                  isSelected ? "ring-2 ring-blue-500 border-blue-500" : ""
                } ${!isLoggedIn ? "opacity-70" : ""}`}
                onClick={() => openStrategy(strategy.id)}
              >
                <CardHeader>
                  <div className="flex items-center gap-3">
                    <div className={`p-3 rounded-lg ${strategy.color}`}>
                      <Icon className="h-6 w-6 text-white" />
                    </div>
                    <div>
                      <CardTitle className="text-lg text-white">{strategy.name}</CardTitle>
                      {isSelected && <Badge className="mt-1 bg-blue-600">Aktif</Badge>}
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <CardDescription className="mb-4 text-gray-400">{strategy.description}</CardDescription>
                  <div className="flex flex-wrap gap-2">
                    {strategy.features.map((feature) => (
                      <Badge key={feature} variant="secondary" className="text-xs bg-gray-800 text-gray-300">
                        {feature}
                      </Badge>
                    ))}
                  </div>
                  {isLoggedIn && (
                    <Button className="w-full mt-4 bg-green-600 hover:bg-green-700 gap-2">
                      <Play className="h-4 w-4" />
                      Start Auto Trading
                    </Button>
                  )}
                </CardContent>
              </Card>
            )
          })}
        </div>

        {/* Info Section */}
        <Card className="mt-8 bg-[#161b22] border-gray-800">
          <CardContent className="py-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-center">
              <div>
                <h3 className="font-semibold text-lg mb-1 text-white">100% Otomatis</h3>
                <p className="text-sm text-gray-400">Trading berjalan sendiri, Anda hanya stop</p>
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-1 text-white">5 Strategi</h3>
                <p className="text-sm text-gray-400">Terminal, Tick Picker, DigitPad, AMT, Sniper</p>
              </div>
              <div>
                <h3 className="font-semibold text-lg mb-1 text-white">Telegram Integration</h3>
                <p className="text-sm text-gray-400">Kontrol dan monitoring dari Telegram</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </main>
    </div>
  )
}
