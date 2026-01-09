# PowerShell script to populate database with realistic movie showtimes

Write-Host "Logging in as admin..."
$loginResponse = Invoke-RestMethod -Uri http://localhost:8000/login -Method Post -Body @{
    username = "admin@test.com"
    password = "admin123"
} -ContentType "application/x-www-form-urlencoded"

$token = $loginResponse.access_token
Write-Host "Admin login successful!"

$headers = @{
    "Authorization" = "Bearer $token"
    "Content-Type" = "application/json"
}

# 30 Popular movies
$movies = @(
    "Superman",
    "Captain America: Brave New World",
    "Thunderbolts",
    "The Fantastic Four: First Steps",
    "Mission: Impossible - The Final Reckoning",
    "Wicked",
    "Sonic the Hedgehog 3",
    "Mufasa: The Lion King",
    "Nosferatu",
    "A Complete Unknown",
    "Paddington in Peru",
    "The Brutalist",
    "Sinners",
    "How to Train Your Dragon",
    "Snow White",
    "Elio",
    "A Minecraft Movie",
    "Lilo and Stitch",
    "Avengers: Doomsday",
    "Zootopia 2",
    "The Amateur",
    "Ballerina",
    "The Karate Kid",
    "Freaky Friday 2",
    "Final Destination: Bloodlines",
    "Michael",
    "From the World of John Wick: Ballerina",
    "Jurassic World: Rebirth",
    "The Accountant 2",
    "Blade"
)

# Theaters in different locations
$theaters = @(
    "AMC Lincoln Square IMAX",
    "Regal Union Square",
    "Cinemark Century City",
    "Alamo Drafthouse Brooklyn",
    "iPic Theaters Fulton Market",
    "AMC Empire 25",
    "Regal Court Street",
    "Showcase Cinema de Lux",
    "Bow Tie Chelsea Cinemas",
    "Nitehawk Cinema Williamsburg"
)

# Showtimes
$showtimes = @("11:30", "14:00", "16:30", "19:00", "21:30")

Write-Host "`nCreating movie showtimes..."
$movieCount = 0

foreach ($movie in $movies) {
    # Each movie plays at 3-4 random theaters
    $numTheaters = Get-Random -Minimum 3 -Maximum 5
    $selectedTheaters = $theaters | Get-Random -Count $numTheaters
    
    foreach ($theater in $selectedTheaters) {
        # Each theater shows 2-3 showtimes
        $numTimes = Get-Random -Minimum 2 -Maximum 4
        $selectedTimes = $showtimes | Get-Random -Count $numTimes
        
        foreach ($time in $selectedTimes) {
            $startTime = "2026-01-15T${time}:00"
            $startHour = [int]$time.Split(':')[0]
            $endHour = $startHour + 2
            $endMinute = $time.Split(':')[1]
            $endTime = "2026-01-15T${endHour}:${endMinute}:00"
            
            $seats = Get-Random -Minimum 120 -Maximum 280
            
            $eventData = @{
                name = $movie
                venue = $theater
                start_time = $startTime
                end_time = $endTime
                total_seats = $seats
            } | ConvertTo-Json

            try {
                $result = Invoke-RestMethod -Uri http://localhost:8001/events -Method Post -Headers $headers -Body $eventData
                Write-Host "[OK] $movie at $theater - $time ($seats seats)" -ForegroundColor Green
                $movieCount++
            }
            catch {
                Write-Host "[FAIL] $movie at $theater - $time" -ForegroundColor Red
            }
        }
    }
}

Write-Host "`nMovies created!"

# 10 Concerts
Write-Host "`nCreating concerts..."
$concerts = @(
    @{name="The Neighbourhood - Hard to Imagine Tour"; venue="Madison Square Garden, New York"; date="2026-02-14T20:00:00"; seats=3500},
    @{name="The 1975 - At Their Very Best"; venue="The O2 Arena, London"; date="2026-03-20T19:30:00"; seats=4200},
    @{name="Chase Atlantic - Lost in Heaven and Hell Tour"; venue="Brooklyn Steel, Brooklyn"; date="2026-02-28T20:00:00"; seats=1800},
    @{name="Slowdive - Everything is Alive Tour"; venue="The Fillmore, San Francisco"; date="2026-04-10T20:00:00"; seats=1200},
    @{name="Anirudh Ravichander Live in Concert"; venue="Nehru Indoor Stadium, Chennai"; date="2026-03-15T18:00:00"; seats=5000},
    @{name="Abdul Hannan - Iraaday Tour"; venue="Karachi Expo Center, Pakistan"; date="2026-05-01T19:00:00"; seats=4500},
    @{name="Don Toliver - Love Sick Tour"; venue="Staples Center, Los Angeles"; date="2026-06-05T20:00:00"; seats=3800},
    @{name="Kendrick Lamar - The Big Steppers Tour"; venue="Crypto.com Arena, Los Angeles"; date="2026-06-12T19:00:00"; seats=4700},
    @{name="Lana Del Rey - Did You Know Tour"; venue="Red Rocks Amphitheatre, Colorado"; date="2026-05-20T19:30:00"; seats=3200},
    @{name="Arctic Monkeys - The Car World Tour"; venue="Wembley Stadium, London"; date="2026-07-18T18:30:00"; seats=5000}
)

$concertCount = 0
foreach ($concert in $concerts) {
    $endTime = ([datetime]$concert.date).AddHours(3).ToString("yyyy-MM-ddTHH:mm:ss")
    
    $eventData = @{
        name = $concert.name
        venue = $concert.venue
        start_time = $concert.date
        end_time = $endTime
        total_seats = $concert.seats
    } | ConvertTo-Json

    try {
        $result = Invoke-RestMethod -Uri http://localhost:8001/events -Method Post -Headers $headers -Body $eventData
        Write-Host "[OK] Created: $($concert.name) - $($concert.seats) seats" -ForegroundColor Green
        $concertCount++
    }
    catch {
        Write-Host "[FAIL] Failed: $($concert.name)" -ForegroundColor Red
    }
}

Write-Host "`nConcerts created!"

Write-Host "`n================================"
Write-Host "Database Population Complete!"
Write-Host "================================"
Write-Host "- $movieCount Movie showtimes added (30 unique movies)"
Write-Host "- $concertCount Concerts added"
Write-Host "Total Events: $($movieCount + $concertCount)"
Write-Host "================================`n"