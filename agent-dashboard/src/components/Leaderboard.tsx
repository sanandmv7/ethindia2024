'use client';

import { useEffect, useState } from 'react';
import { database, ref, onValue } from '@/firebase/firebase';
import { LeaderboardEntry } from '@/types';
import { DataSnapshot } from 'firebase/database';

export default function Leaderboard() {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Updated reference path to match data structure
    const leaderboardRef = ref(database, 'leaderboard/current/entries');

    const unsubscribe = onValue(leaderboardRef, (snapshot: DataSnapshot) => {
      console.log('Firebase data:', snapshot.val());
      const data = snapshot.val();
      if (data) {
        // Filter out null entries and convert to array
        const leaderboardData = Object.values(data).filter(entry => entry !== null) as LeaderboardEntry[];
        const sortedData = leaderboardData.sort((a, b) => b.score - a.score);
        console.log('Sorted data:', sortedData);
        setEntries(sortedData);
      } else {
        console.log('No data found in Firebase');
        setEntries([]);
      }
      setLoading(false);
    }, (error) => {
      console.error('Firebase error:', error);
      setLoading(false);
    });

    return () => unsubscribe();
  }, []);

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <p className="text-center">Loading leaderboard...</p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl text-black font-semibold">Leaderboard</h2>
        <a 
          href="/history" 
          className="text-blue-600 hover:text-blue-800 text-sm"
        >
          View History
        </a>
      </div>
      
      <div className="space-y-4">
        {entries.length === 0 ? (
          <p className="text-center text-gray-500">No entries yet</p>
        ) : (
          entries.map((entry, index) => (
            <div key={`${entry.twitter_handle}-${entry.post_link}`} className="border-b pb-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className="font-bold text-lg">{index + 1}</span>
                  <div>
                    <a 
                      href={entry.post_link} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:text-blue-800"
                    >
                      @{entry.twitter_handle}
                    </a>
                    <p className="text-sm text-gray-500 font-mono">{entry.wallet_address}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="font-semibold text-black">{entry.score} points</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}